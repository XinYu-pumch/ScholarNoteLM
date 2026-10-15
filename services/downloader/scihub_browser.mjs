// Production browser transport. Network operations use page navigation exclusively.
import {chromium} from '@playwright/test';
import readline from 'node:readline';
import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
const directory=path.resolve(process.argv[2]);
const MAX=250*1024*1024, HTML_MAX=4*1024*1024;
const selector='div.pdf iframe[src], div.pdf object[data], div.download a[href], embed[type="application/pdf"][src], iframe#pdf[src]';
const sessions=new Map(),closedSessions=new Set(),verifiedCookies=new Map();let server,browser,starting,stopping=false;
const reply=value=>{if(!stopping)process.stdout.write(JSON.stringify(value)+'\n');};
const failure=(kind,message)=>Object.assign(new Error(message),{kind});
const classify=error=>error.kind || (/timeout|timed out/i.test(String(error))?'timeout':/ERR_CERT|certificate/i.test(String(error))?'tls_certificate':/closed|crash|disconnected/i.test(String(error))?'browser_error':'network_error');
const messages={timeout:'浏览器导航、渲染或文件传输超时',tls_certificate:'浏览器 TLS 证书验证失败',browser_error:'Chromium 页面或浏览器异常退出',network_error:'浏览器网络访问失败',browser_unavailable:'无法启动项目内 Playwright Chromium，请检查 Node、Playwright 和浏览器运行时',response_too_large:'浏览器响应超过大小限制'};
async function launch(){
 if(!starting)starting=(async()=>{
  try{
   // Leave proxy options unset: Chromium follows the native system proxy and
   // its change notifications, including PAC. Do not freeze a startup snapshot
   // in --proxy-server / context.proxy or force --no-proxy-server.
   server=await chromium.launchServer({headless:true,host:'127.0.0.1',downloadsPath:directory,timeout:10000});
   browser=await chromium.connect(server.wsEndpoint(),{timeout:10000});
   reply({event:'browser',pid:server.process().pid,version:browser.version()});
   browser.on('disconnected',()=>{if(!stopping)void shutdown(1);});
  }catch{throw failure('browser_unavailable',messages.browser_unavailable);}
 })();
 await starting;
}
async function close(key){
 closedSessions.add(key);
 const state=sessions.get(key);if(!state)return;
 sessions.delete(key);state.closed=true;
 await state.context.close().catch(()=>{});
 await Promise.allSettled([...state.work]);
 for(const file of state.files)await fs.rm(file,{force:true}).catch(()=>{});
}
async function stateFor(key){
 await launch();
 if(closedSessions.has(key)||stopping)throw failure('browser_error',messages.browser_error);
 if(!sessions.has(key)){
  const context=await browser.newContext({acceptDownloads:true,serviceWorkers:'block'});
  if(closedSessions.has(key)||stopping){await context.close();throw failure('browser_error',messages.browser_error);}
  sessions.set(key,{context,referer:'',work:new Set(),files:new Set(),closed:false});
 }
 return sessions.get(key);
}
async function get(m){
 const state=await stateFor(m.session);
 const metrics={transport:'playwright-chromium',browserVersion:browser.version(),browserRequests:0,automaticRequests:0,blockedAutomaticRequests:0,failedRequests:0};
 let timer,page,download,latestResponse,mainResponse,transportFailure;
 const body=path.join(directory,randomUUID()+'.body');state.files.add(body);let keepPage=false;
 // All awaited operations (including response.body/download.saveAs) share one deadline.
 const work=(async()=>{
  if(state.entryPage){await state.entryPage.close().catch(()=>{});state.entryPage=null;}
  if(m.role==='entry'){
   const jar=verifiedCookies.get(new URL(m.url).origin);
   if(jar)await state.context.addCookies(jar.filter(c=>c.expires===-1||c.expires>Date.now()/1000));
  }
  page=await state.context.newPage();let first=true;
  page.on('request',request=>{metrics.browserRequests++;if(!(request.isNavigationRequest()&&request.frame()===page.mainFrame()))metrics.automaticRequests++;});
  page.on('requestfailed',()=>metrics.failedRequests++);
  // Do not let embedded PDF viewers or advertisements bypass Python's file semaphore.
  // Ordinary JS/CSS may render the DOM. Altcha protocol requests are explicit;
  await page.route('**/*',async route=>{
   const request=route.request();const main=request.isNavigationRequest()&&request.frame()===page.mainFrame();
   if(!/^https?:/.test(request.url()) || (!main&&/\/captcha\/(challenge|solution)\//.test(new URL(request.url()).pathname)&&request.url()!==state.protocolURL) || (!main&&(['document','image','media','font','other'].includes(request.resourceType()) || /\.pdf(?:[?#]|$)/i.test(request.url())))){
    metrics.blockedAutomaticRequests++;await route.abort().catch(()=>{});return;
   }
   if(main&&first)first=false;
   await route.continue().catch(()=>{});
  });
  // At response headers, block PDF subrequests even when their URL has no .pdf
  // suffix. This prevents script-triggered file transfers outside explicit locks.
  const cdp=await state.context.newCDPSession(page);
  await cdp.send('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Response'}]});
  cdp.on('Fetch.requestPaused',async event=>{
   const headers=event.responseHeaders||[];
   const pdf=headers.some(h=>h.name.toLowerCase()==='content-type'&&/pdf|octet-stream/i.test(h.value));
   const isMain=event.resourceType==='Document'&&event.frameId===mainFrame;
   if(isMain)mainResponse={status:event.responseStatusCode,url:event.request.url,headers:Object.fromEntries(headers.map(h=>[h.name.toLowerCase(),h.value]))};
   const large=headers.some(h=>h.name.toLowerCase()==='content-length'&&Number(h.value)>MAX);
   if(large&&isMain)transportFailure=failure('response_too_large',messages.response_too_large);
   if((pdf&&!isMain)||large){metrics.blockedAutomaticRequests+=!isMain?1:0;await cdp.send('Fetch.failRequest',{requestId:event.requestId,errorReason:'Aborted'}).catch(()=>{});}
   else await cdp.send('Fetch.continueResponse',{requestId:event.requestId}).catch(()=>{});
  });
  const {frameTree}=await cdp.send('Page.getFrameTree');const mainFrame=frameTree.frame.id;
  let resolveDownload;const gotDownload=new Promise(resolve=>resolveDownload=resolve);
  page.on('download',value=>{download=value;resolveDownload(value);});
  page.on('response',response=>{if(response.request().isNavigationRequest()&&response.request().frame()===page.mainFrame())latestResponse=response;});
  let response;
  try{response=await page.goto(m.url,{waitUntil:'domcontentloaded',timeout:m.timeout*1000,...(m.role==='file'&&state.referer?{referer:state.referer}:{})});}
  catch(error){
   if(transportFailure)throw transportFailure;
   if(mainResponse?.status&&mainResponse.status!==200){
    await fs.writeFile(body,'');
    return {status_code:mainResponse.status,url:mainResponse.url,headers:{'content-type':mainResponse.headers['content-type']||'', 'retry-after':mainResponse.headers['retry-after']||''},body,method:'browser-response-status',metrics};
   }
   if(!/download|ERR_ABORTED/i.test(String(error)))throw error;
   if(!download)download=await Promise.race([gotDownload,new Promise(resolve=>setTimeout(()=>resolve(null),150))]);
   if(!download)throw error;
  }
  response=response||latestResponse;
  let headers=response?await response.allHeaders():mainResponse?.headers||{},status=response?.status()||mainResponse?.status,url=response?.url()||mainResponse?.url||m.url,method;
  if(!status)throw failure('network_error',messages.network_error);
  if(download){
   await download.saveAs(body);
   if(await download.failure())throw failure('network_error',messages.network_error);
   url=download.url();method='browser-download';
  }else{
   if(!response)throw failure('network_error',messages.network_error);
   if((headers['content-type']||'').includes('pdf')){
    const bytes=await response.body();if(bytes.length>MAX)throw failure('response_too_large',messages.response_too_large);
    await fs.writeFile(body,bytes);method='browser-response-body';
   }else{
    if(status===200){
     await page.waitForFunction(()=>{
      const nodes=[...document.querySelectorAll('meta[name="citation_pdf_url"], a[href], object[data], iframe[src], embed[src]')];
      return nodes.some(n=>{const v=n.getAttribute('content')||n.getAttribute('href')||n.getAttribute('data')||n.getAttribute('src')||'';
       return v&&!/^(data:|about:|javascript:|blob:|#)/i.test(v)&& (n.tagName!=='A'||n.closest('.download,.pdf')||n.matches('.download')||/\/storage\/|\.pdf(?:[?#]|$)/i.test(v));}) || document.querySelector('altcha-widget') || /captcha|checking your browser|are you.*robot/i.test(document.body?.innerText||'');
     },null,{timeout:Math.min(1500,Math.max(1,m.timeout*1000-250))}).catch(error=>{if(!/timeout/i.test(String(error)))throw error;});
    }
    const html=await page.evaluate(()=>{
     const copy=document.documentElement.cloneNode(true);
     for(const n of copy.querySelectorAll('*'))for(const a of [...n.attributes])if(/^data:/i.test(a.value)&&a.value.length>512)n.setAttribute(a.name,'data:STRIPPED');
     return copy.outerHTML;
    });if(Buffer.byteLength(html)>HTML_MAX)throw failure('response_too_large',messages.response_too_large);
    await fs.writeFile(body,html);method='browser-rendered-dom';url=page.url();
    if(m.role==='entry'){state.referer=url;state.entryPage=page;keepPage=true;}
   }
  }
  if((await fs.stat(body)).size>MAX)throw failure('response_too_large',messages.response_too_large);
  return {status_code:status,url,headers:{'content-type':headers['content-type']||'', 'retry-after':headers['retry-after']||''},body,method,metrics};
 })();
 state.work.add(work);work.catch(()=>{});
 // Chromium temporary downloads are also bounded while still in flight.
 const sizeWatch=setInterval(async()=>{
  if(!download)return;
  const files=await fs.readdir(directory).catch(()=>[]);
  for(const name of files){const stat=await fs.stat(path.join(directory,name)).catch(()=>null);if(stat?.isFile()&&stat.size>MAX){void close(m.session);break;}}
 },100);
 try{
  return await Promise.race([work,new Promise((_,reject)=>timer=setTimeout(()=>reject(failure('timeout',messages.timeout)),m.timeout*1000))]);
 }catch(error){
  const kind=classify(error);throw Object.assign(failure(kind,messages[kind]||messages.network_error),{metrics});
 }finally{
  clearTimeout(timer);clearInterval(sizeWatch);
  // Closing the page aborts slow response bodies and partial native downloads.
  if(!keepPage||state.closed)await page?.close().catch(()=>{});
  await Promise.allSettled([work]);state.work.delete(work);
 }
}

// Only the bounded challenge protocol uses fetch inside a real, already navigated
// Chromium page. Article/PDF requests remain page.goto/native downloads.
async function protocol(m){
 const state=await stateFor(m.session),page=state.entryPage;
 if(!page||page.isClosed())throw failure('browser_error','缺少验证页面');
 const target=new URL(m.url),source=new URL(page.url());
 if(target.origin!==source.origin||!/^\/captcha\/(challenge|solution)\/[A-Za-z0-9_-]+$/.test(target.pathname))throw failure('network_error','验证地址无效');
 let timer;state.protocolURL=m.url;
 const work=page.evaluate(async({url,method,payload,timeout})=>{
  const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),timeout*1000);
  try{
   const r=await fetch(url,{method,credentials:'same-origin',redirect:'error',signal:abort.signal,
    ...(method==='POST'?{headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{})});
   const reader=r.body.getReader(),parts=[];let size=0;
   while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>65536){await reader.cancel();throw Error('response too large');}parts.push(value);}
   const bytes=new Uint8Array(size);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
   return {status_code:r.status,url:r.url,text:new TextDecoder().decode(bytes),headers:{'retry-after':r.headers.get('retry-after')||''}};
  }finally{clearTimeout(timer);}
 },{url:m.url,method:m.method,payload:m.payload,timeout:m.timeout});
 state.work.add(work);work.catch(()=>{});
 try{
  const data=await Promise.race([work,new Promise((_,reject)=>timer=setTimeout(()=>reject(failure('timeout',messages.timeout)),m.timeout*1000))]);
  return {...data,method:'browser-challenge-fetch',metrics:{transport:'playwright-chromium',browserVersion:browser.version(),explicitProtocolRequests:1}};
 }catch(error){await page.close().catch(()=>{});throw error;}
 finally{clearTimeout(timer);state.protocolURL=null;await Promise.allSettled([work]);state.work.delete(work);}
}
async function rememberCookies(m){
 const state=await stateFor(m.session);if(!state.entryPage)throw failure('browser_error','缺少验证页面');
 const origin=new URL(state.entryPage.url()).origin;
 verifiedCookies.set(origin,await state.context.cookies(origin));return {};
}

async function shutdown(code=0){
 if(stopping)return;stopping=true;
 const watchdog=setTimeout(()=>{try{if(process.platform!=='win32'&&server)process.kill(-server.process().pid,'SIGKILL');}catch{}process.exit(code||1);},1500);
 await Promise.allSettled([...sessions.keys()].map(close));
 if(server)await server.close().catch(()=>{});
 await fs.rm(directory,{recursive:true,force:true,maxRetries:3}).catch(()=>{});
 clearTimeout(watchdog);process.exit(code);
}
const input=readline.createInterface({input:process.stdin});
input.on('line',line=>{
 let m;try{m=JSON.parse(line);}catch{void shutdown(1);return;}
 const operation=m.op==='get'?get(m):m.op==='protocol'?protocol(m):m.op==='rememberCookies'?rememberCookies(m):m.op==='close'?close(m.session).then(()=>({})):Promise.reject(failure('browser_error','未知浏览器操作'));
 operation.then(data=>reply({id:m.id,data})).catch(error=>{const kind=classify(error);reply({id:m.id,kind,error:messages[kind]||messages.network_error,metrics:error.metrics});});
});
input.on('close',()=>void shutdown());
process.on('SIGTERM',()=>void shutdown());process.on('SIGINT',()=>void shutdown());
