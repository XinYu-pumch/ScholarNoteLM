/** Conversation polling regression. In-memory RPC fixtures only; no research data/server. */
import {chromium,expect} from '@playwright/test';
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import path from 'node:path';
const root=process.cwd(),tmp=await mkdtemp(path.join(root,'tmp/conversation-loading-ui-'));let server,browser;
try{
 await writeFile(path.join(tmp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
 await writeFile(path.join(tmp,'main.jsx'),`import React from 'react';import {createRoot} from 'react-dom/client';import Reader from '/@fs/${root}/apps/desktop/src/Reader.tsx';import '/@fs/${root}/apps/desktop/src/styles.css';import '/@fs/${root}/apps/desktop/src/design.css';
 window.calls=[];window.thread={id:'thread',pmid:'1',name:'Existing conversation',state:'done',revision:1,source:'v1',sourceKind:'abstract',profileId:'p',model:'fixture',error:'',messages:[{id:'turn1',question:'Old question',text:'Preserved answer',reasoning:'Preserved reasoning',state:'done',model:'fixture'}]};
 window.project={id:'test',name:'Isolated reader',papers:[{id:'PMID-1',title:'Fixture paper',journal:'Fixture',year:'2026'}],notes:{}};
 createRoot(document.getElementById('root')).render(<Reader/>);`);
 server=await createServer({configFile:false,root:tmp,cacheDir:path.join(tmp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','@tauri-apps/api/core','@tauri-apps/api/event','react-markdown','remark-gfm']},server:{host:'127.0.0.1',port:0,fs:{allow:[root]}},plugins:[{name:'fixtures',enforce:'pre',resolveId(src,importer){if(importer?.startsWith(root+'/apps/desktop/src/')){if(src==='./context')return '\0ctx';if(src==='./research-api')return '\0rpc';}},load(id){if(id==='\0ctx')return `export function useApp(){return {state:{defaultContentLanguage:'zh'},project:window.project,paperId:'PMID-1',setPaperId:()=>{},setPage:()=>{},notify:()=>{},updateProject:()=>{}}}`;
 if(id==='\0rpc')return `export * from '/@fs/${root}/apps/desktop/src/research-api.ts';
 async function fixtureRpc(action,args={}){
 window.calls.push({action,args});
 if(action==='profile.list')return {profiles:[{id:'p',name:'Fixture',model:'fixture',models:['fixture']}],activeProfile:'p'};
 if(action==='reader.recent')return {items:[]};
 if(action==='reader.document')return {pmid:'1',title:'Fixture paper',abstract:'Original abstract',hasPdf:false,ready:true,version:'v1',kind:'abstract'};
 if(action==='reader.progress')return {thread:'thread'};
 if(action==='reader.list')return {threads:[{...window.thread,messages:[]}]};
 if(action==='reader.get'){
  const snapshot=JSON.parse(JSON.stringify(window.thread));
  if(window.failNext){window.failNext=false;throw Error('Temporary read failure');}
  if(window.holdNext){window.holdNext=false;await new Promise(resolve=>window.release=resolve);return snapshot;}
  return args.revision===snapshot.revision?{id:snapshot.id,revision:snapshot.revision,unchanged:true}:snapshot;
 }
 if(action==='reader.start'){window.thread={...window.thread,revision:window.thread.revision+1,state:'running',messages:[...window.thread.messages,{id:'turn2',question:args.question,text:'New partial answer',reasoning:'',state:'running',model:'fixture'}]};return window.thread;}
 if(action==='reader.cancel'){window.thread={...window.thread,revision:window.thread.revision+1,state:'cancelled',messages:window.thread.messages.map(t=>({...t,state:'done'}))};return window.thread;}
 throw Error(action);
 }
 const originalFetch=window.fetch.bind(window);window.fetch=async(url,options)=>{if(!String(url).startsWith('/__research'))return originalFetch(url,options);const {action,args}=JSON.parse(options.body);try{return new Response(JSON.stringify({ok:true,data:await fixtureRpc(action,args)}),{headers:{'Content-Type':'application/json'}});}catch(e){return new Response(JSON.stringify({ok:false,error:e.message}),{headers:{'Content-Type':'application/json'}});}};`;
 }}]});await server.listen();
 browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'});const page=await browser.newPage({viewport:{width:1500,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 await page.goto(`http://127.0.0.1:${server.httpServer.address().port}`);
 await expect(page.locator('.paper-chat-messages')).toContainText('Preserved answer');
 await expect.poll(()=>page.evaluate(()=>window.calls.filter(c=>c.action==='reader.get').length),{timeout:7000}).toBeGreaterThan(1);
 expect(await page.evaluate(()=>window.calls.filter(c=>c.action==='reader.get').at(-1).args.revision)).toBe(1);
 await page.evaluate(()=>{window.failNext=true;});
 await expect(page.getByRole('alert')).toContainText('Temporary read failure',{timeout:7000});
 await page.evaluate(()=>{window.thread={...window.thread,revision:2,messages:window.thread.messages.map(t=>({...t,text:'Updated existing answer'}))};});
 await expect(page.locator('.paper-chat-messages')).toContainText('Updated existing answer',{timeout:7000});
 // A slow poll started before Send must not overwrite the immediate mutation result.
 await page.evaluate(()=>{window.holdNext=true;});
 await expect.poll(()=>page.evaluate(()=>typeof window.release),{timeout:7000}).toBe('function');
 await page.getByLabel('向这篇文献提问',{exact:true}).fill('New question');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.locator('.paper-chat-messages')).toContainText('New partial answer');
 await page.evaluate(()=>window.release());
 await expect.poll(()=>page.evaluate(()=>window.calls.filter(c=>c.action==='reader.get').at(-1).args.revision),{timeout:3000}).toBe(3);
 await expect(page.locator('.paper-chat-turn')).toHaveCount(2);await expect(page.locator('.paper-chat-messages')).toContainText('New partial answer');
 await page.getByRole('button',{name:'停止',exact:true}).click();await expect(page.getByRole('button',{name:'发送',exact:true})).toBeVisible();
 expect(errors).toEqual([]);
 console.log(JSON.stringify({passed:true,checks:['restore historical conversation','conditional idle polling','retry after transient read failure','external updates visible','late poll cannot replace Send result','active polling and cancellation','no remote requests']}));
}finally{await browser?.close();await server?.close();await rm(tmp,{recursive:true,force:true});}
