/** Controlled streams and PubMed jobs only; never changes a research project. */
import {chromium,webkit,expect} from '@playwright/test';
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
const root=process.cwd(),tmp=await mkdtemp(path.join(root,'tmp/search-fixes-ui-'));let server,browser;
try{
 await writeFile(path.join(tmp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
 await writeFile(path.join(tmp,'main.jsx'),`import React from 'react';import {createRoot} from 'react-dom/client';import SearchChat from '/@fs/${root}/apps/desktop/src/SearchChat.tsx';import Workbench from '/@fs/${root}/apps/desktop/src/SearchWorkbench.tsx';import {invalidate} from '/@fs/${root}/apps/desktop/src/query-cache.ts';import {forgetSearchSessions} from '/@fs/${root}/apps/desktop/src/search-chat-sessions.ts';import '/@fs/${root}/apps/desktop/src/styles.css';import '/@fs/${root}/apps/desktop/src/workbench.css';import '/@fs/${root}/apps/desktop/src/conversation.css';
window.calls=[];window.notices=[];window.added=[];window.job=null;window.hold=false;
const filters={start:'',end:'',sort:'relevance',mode:'explore',limit:30,jcr:false,quartiles:[],unknown:'keep'};
const query=(id,values={})=>({id,name:id,text:id+'[tiab]',source:'manual',enabled:true,archived:false,revision:1,error:'',filters,...values});
window.data={queries:[query('current',{xmlExists:true}),query('missing'),query('changed',{xmlExists:true,stale:true}),query('disabled',{enabled:false}),query('archived',{archived:true}),query('import',{source:'import'}),query('empty',{text:''})],chats:[],conversation:[],corpus:{papers:[],included:0,excluded:0,snapshot:'fixture'}};
window.thread={id:'thread',name:'追加对话',messages:[{role:'user',text:'补充检索方向',created:1},{role:'assistant',text:'### 追加检索\\n\\n'+String.fromCharCode(96).repeat(3)+'pubmed\\nkidney[tiab] AND immunity[tiab]\\n'+String.fromCharCode(96).repeat(3),created:2}]};
const realFetch=window.fetch.bind(window);window.fetch=async(url,options)=>{
 if(!String(url).startsWith('/__research'))return realFetch(url,options);
 const {action,args}=JSON.parse(options.body);window.calls.push({action,args});let result;
 if(action==='chat'){window.thread.messages.push({role:'user',text:args.message,created:3});const encoder=new TextEncoder();return new Response(new ReadableStream({start(controller){window.push=(text,reasoning='')=>{window.latest=text;window.latestReasoning=reasoning;controller.enqueue(encoder.encode(JSON.stringify({type:'update',text,reasoning,emittedAt:Date.now()})+'\\n'));};window.finish=()=>{window.thread.messages.push({role:'assistant',text:window.latest,reasoning:window.latestReasoning,created:4});controller.enqueue(encoder.encode(JSON.stringify({type:'done',ok:true,data:window.thread.messages})+'\\n'));controller.close();};}}));}
 else if(action==='profile.list')result={profiles:[],activeProfile:''};
 else if(action==='chat.list')result=[window.thread];
 else if(action==='chat.get')result=window.thread;
 else if(action==='zotero.status')result=null;
 else if(action==='workspace')result=window.data;
 else if(action==='query.save'){Object.assign(window.data.queries.find(q=>q.id===args.id),args);result=window.data;}
 else if(action==='query.run'){if(window.hold)await new Promise(resolve=>window.job={resolve,executionId:args.executionId});else{const q=window.data.queries.find(q=>q.id===args.id);q.xmlExists=true;q.stale=false;}result=window.data;}
 else if(action==='query.cancel'){if(window.job?.executionId===args.executionId){window.job.resolve();window.job=null;}result={cancelled:true};}
 else throw Error('Unexpected RPC '+action);
 return new Response(JSON.stringify({ok:true,data:structuredClone(result)}),{headers:{'Content-Type':'application/json'}});
};
const tree=createRoot(document.getElementById('root'));let generation=0;window.show=mode=>{forgetSearchSessions('test',['thread']);invalidate(undefined,undefined,true);localStorage.setItem('scholar-chat:test','thread');tree.render(<div className="main-content" style={{height:'100vh',display:'flex',flexDirection:'column'}}>{mode==='chat'?<SearchChat key={++generation} queries={[]} onAdd={async q=>{if(window.failAdd)throw Error('模拟保存失败');window.added.push(q);if(window.holdAdd)await new Promise(resolve=>window.releaseAdd=resolve);}}/>:<Workbench key={++generation}/>}</div>);};window.show('chat');`);
 server=await createServer({configFile:false,root:tmp,cacheDir:path.join(tmp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','@tauri-apps/api/core','react-markdown','remark-gfm']},server:{host:'127.0.0.1',port:0,fs:{allow:[root]}},plugins:[{name:'mocks',enforce:'pre',resolveId(src,importer){if(importer?.startsWith(root+'/apps/desktop/src/')){if(src==='./context')return '\0ctx';if(src==='./download-api')return '\0download';}},load(id){if(id==='\0ctx')return `export const useApp=()=>({notify:text=>window.notices.push(text),setPage:()=>{},project:{id:'test',name:'测试项目',papers:[]}});`;if(id==='\0download')return `export const useDownloads=()=>({data:{batches:[],assets:{}}});export const startDownload=async()=>({count:0});`;}}]});await server.listen();
 const useWebkit=process.env.UI_BROWSER==='webkit';browser=await (useWebkit?webkit:chromium).launch({headless:true,...(useWebkit?{}:{channel:'chrome'})});const page=await browser.newPage({viewport:{width:1400,height:900},...(useWebkit?{}:{permissions:['clipboard-read','clipboard-write']})});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());await page.goto(`http://127.0.0.1:${server.httpServer.address().port}`);
 // Historical responses without structured metadata still expose inline controls.
 await expect(page.getByRole('button',{name:'复制检索式：追加检索'})).toBeVisible();await page.getByRole('button',{name:'发送到文献来源：追加检索'}).click();expect(await page.evaluate(()=>window.added[0].text)).toBe('kidney[tiab] AND immunity[tiab]');
 await page.getByRole('textbox',{name:'研究需求'}).fill('再补充');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.getByRole('button',{name:'停止生成'})).toBeVisible();
 // A stream update between pointerdown/up must preserve the same historical button.
 await page.evaluate(()=>window.push('本地流式开始'));
 const previous=page.getByRole('button',{name:'发送到文献来源：追加检索'});await previous.scrollIntoViewIfNeeded();
 const previousBox=await previous.boundingBox();await page.mouse.move(previousBox.x+previousBox.width/2,previousBox.y+previousBox.height/2);await page.mouse.down();
 const beforeAdds=await page.evaluate(()=>{window.originalButton=document.querySelector('[aria-label="发送到文献来源：追加检索"]');window.push('流式继续，不应替换旧按钮');return window.added.length;});
 await page.waitForTimeout(120);expect(await page.evaluate(()=>window.originalButton.isConnected)).toBe(true);await page.mouse.up();
 await expect.poll(()=>page.evaluate(()=>window.added.length)).toBe(beforeAdds+1);
 // Saving one proposal has its own pending state and does not freeze the live reply.
 await page.evaluate(()=>{window.holdAdd=true;});await previous.click();await expect(previous).toBeDisabled();
 await page.evaluate(()=>window.push('保存期间仍可显示的新内容'));
 await expect(page.locator('.chat-message.assistant').last()).toContainText('保存期间仍可显示的新内容');
 await expect(page.getByRole('button',{name:'停止生成'})).toBeEnabled();await page.evaluate(()=>{window.holdAdd=false;window.releaseAdd();});await expect(previous).toBeEnabled();
 await page.evaluate(()=>{window.failAdd=true;});await previous.click();await expect(page.getByRole('alert')).toContainText('模拟保存失败');await expect(previous).toBeEnabled();await page.evaluate(()=>{window.failAdd=false;});
 const fence='```';let text='### 流式检索\n\n'+fence+'PuBmEd\nkidney[tiab] AND complement[tiab]\n';
 await page.evaluate(text=>window.push(text),text);await expect(page.getByRole('button',{name:'复制检索式：流式检索'})).toHaveCount(0);
 text+=fence+'\n\n';await page.evaluate(text=>window.push(text),text);await expect(page.getByRole('button',{name:'复制检索式：流式检索'})).toBeVisible();await page.getByRole('button',{name:'发送到文献来源：流式检索'}).click();expect(await page.evaluate(()=>window.added.at(-1).text)).toBe('kidney[tiab] AND complement[tiab]');await expect(page.getByRole('button',{name:'停止生成'})).toBeVisible();
 text+='继续分析材料。\n\n'.repeat(100);await page.evaluate(text=>window.push(text),text);
 const pane=page.locator('.wb-conversation');await pane.evaluate(el=>{el.scrollTop=el.scrollHeight;});await page.waitForTimeout(80);
 // A small upward wheel movement used to stay inside the 90px follow threshold.
 const box=await pane.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.wheel(0,-45);await page.waitForTimeout(150);const top=await pane.evaluate(el=>el.scrollTop);
 for(let i=0;i<8;i++){text+='新的流式内容。\n\n';await page.evaluate(text=>window.push(text),text);await page.waitForTimeout(35);}
 expect(Math.abs(await pane.evaluate(el=>el.scrollTop)-top)).toBeLessThan(3);
 // Pointer press pauses following before the browser dispatches a scrollbar scroll.
 await page.getByRole('button',{name:'对话目录',exact:true}).click();await page.getByRole('button',{name:'回到最新',exact:true}).click();
 await pane.dispatchEvent('pointerdown',{pointerId:1,clientX:box.x+box.width-2,clientY:box.y+100});await pane.evaluate(el=>{el.scrollTop-=35;});await page.waitForTimeout(60);const dragged=await pane.evaluate(el=>el.scrollTop);
 text+='拖动时继续到来的内容。\n\n'.repeat(6);await page.evaluate(text=>window.push(text),text);expect(Math.abs(await pane.evaluate(el=>el.scrollTop)-dragged)).toBeLessThan(3);await page.evaluate(()=>window.dispatchEvent(new PointerEvent('pointerup')));
 await page.getByRole('button',{name:'对话目录',exact:true}).click();await page.getByRole('button',{name:'回到最新',exact:true}).click();text+='最新消息。\n\n';await page.evaluate(text=>window.push(text),text);await expect.poll(()=>pane.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight)).toBeLessThan(3);

 const liveButton=page.getByRole('button',{name:'发送到文献来源：流式检索'});await liveButton.scrollIntoViewIfNeeded();const liveBox=await liveButton.boundingBox();await page.mouse.move(liveBox.x+liveBox.width/2,liveBox.y+liveBox.height/2);await page.mouse.down();
 const liveCount=await page.evaluate(()=>{window.originalLiveButton=document.querySelector('[aria-label="发送到文献来源：流式检索"]');return window.added.length;});text+='尾部更新。';await page.evaluate(text=>window.push(text),text);await page.waitForTimeout(120);expect(await page.evaluate(()=>window.originalLiveButton.isConnected)).toBe(true);await page.mouse.up();await expect.poll(()=>page.evaluate(()=>window.added.length)).toBe(liveCount+1);
 // Exercise long reasoning bursts: collapsed history stays absent from the DOM.
 await page.evaluate(text=>{window.sentText=text;window.burstStarted=performance.now();window.frameGaps=[];window.previousFrame=performance.now();window.measuring=true;const frame=now=>{window.frameGaps.push(now-window.previousFrame);window.previousFrame=now;if(window.measuring)requestAnimationFrame(frame);};requestAnimationFrame(frame);window.burstCount=0;window.burstTimer=setInterval(()=>{window.burstCount++;window.push(window.sentText,'长篇思考内容。'.repeat(2500)+String(window.burstCount));},20);},text);
 await page.waitForTimeout(2200);const timing=await page.evaluate(()=>{clearInterval(window.burstTimer);window.measuring=false;const gaps=window.frameGaps.sort((a,b)=>a-b);return {periodMs:performance.now()-window.burstStarted,updates:window.burstCount,p95FrameGapMs:gaps[Math.floor(gaps.length*.95)],maxFrameGapMs:Math.max(...gaps)};});
 const traces=await page.evaluate(()=>window.scholarSearchStreamDiagnostics());expect(traces.at(-1).received).toBeGreaterThan(traces.at(-1).rendered);expect(traces.at(-1).maxTransportMs).toBeLessThan(1000);console.log('stream timings',JSON.stringify(timing));
 // A final update immediately followed by done must survive the pending UI timer.
 text+='最终完整文本';await page.evaluate(text=>window.push(text,'最终思考'),text);
 await page.evaluate(()=>window.finish());await expect(page.getByRole('button',{name:'停止生成'})).toHaveCount(0);await expect(page.getByRole('button',{name:/复制检索式：/})).toHaveCount(2);await expect(page.locator('.chat-message.assistant').last()).toContainText('最终完整文本');await expect(page.locator('.chat-foldout-content')).toHaveText(['']);
 // Only missing/stale active queries run; the others are skipped.
 await page.evaluate(()=>window.show('workbench'));await expect(page.getByRole('button',{name:/更新待处理检索/})).toBeEnabled();await page.getByRole('button',{name:/更新待处理检索/}).click();await expect(page.getByRole('button',{name:/更新待处理检索/})).toBeDisabled();
 await expect.poll(()=>page.evaluate(()=>window.calls.filter(c=>c.action==='query.run').map(c=>c.args.id))).toEqual(['missing','changed']);await expect(page.getByRole('button',{name:'中止检索'})).toHaveCount(0);expect(await page.evaluate(()=>window.calls.filter(c=>c.action==='query.run').every(c=>c.args.onlyPending&&c.args.executionId))).toBe(true);
 // Stopping a current query prevents the next batch entry from starting.
 await page.evaluate(()=>{window.data.queries.find(q=>q.id==='missing').xmlExists=false;window.data.queries.find(q=>q.id==='changed').stale=true;window.hold=true;window.calls=[];window.show('workbench');});await expect(page.getByRole('button',{name:/更新待处理检索/})).toBeEnabled();await page.getByRole('button',{name:/更新待处理检索/}).click();await expect.poll(()=>page.evaluate(()=>!!window.job)).toBe(true);await page.getByRole('button',{name:'中止检索',exact:true}).click();await expect(page.getByRole('button',{name:/更新待处理检索/})).toBeEnabled();await page.waitForTimeout(2200);expect(await page.evaluate(()=>window.calls.filter(c=>c.action==='query.run').map(c=>c.args.id))).toEqual(['missing']);expect(await page.evaluate(()=>window.calls.filter(c=>c.action==='query.cancel').length)).toBe(1);
 // Stop during the inter-query delay, without a network job.
 await page.evaluate(()=>{window.hold=false;window.calls=[];});await page.getByRole('button',{name:/更新待处理检索/}).click();await expect(page.getByRole('status')).toContainText('等待 2 秒');await page.getByRole('button',{name:'中止检索',exact:true}).click();await page.waitForTimeout(2200);expect(await page.evaluate(()=>window.calls.filter(c=>c.action==='query.run').map(c=>c.args.id))).toEqual(['missing']);
 // Individual runs also have a stop control and use explicit rerun semantics.
 await page.evaluate(()=>{window.hold=true;window.calls=[];});await page.getByRole('button',{name:'执行 current',exact:true}).click();await expect.poll(()=>page.evaluate(()=>!!window.job)).toBe(true);await page.getByRole('button',{name:'中止检索',exact:true}).click();await expect(page.getByRole('button',{name:'中止检索',exact:true})).toHaveCount(0);expect(await page.evaluate(()=>window.calls.find(c=>c.action==='query.run').args.onlyPending)).toBe(false);
 // Full rerun includes current enabled queries, unlike pending-only updates.
 await page.evaluate(()=>{window.hold=false;window.calls=[];});await page.getByRole('button',{name:'全部重新检索',exact:true}).click();
 await expect.poll(()=>page.evaluate(()=>window.calls.filter(c=>c.action==='query.run').length),{timeout:10000}).toBe(3);
 expect(await page.evaluate(()=>window.calls.filter(c=>c.action==='query.run').map(c=>c.args.id))).toEqual(['current','missing','changed']);
 expect(await page.evaluate(()=>window.calls.filter(c=>c.action==='query.run').every(c=>c.args.force&&!c.args.onlyPending))).toBe(true);
 await expect(page.getByRole('button',{name:'全部重新检索',exact:true})).toBeEnabled();
 // Read a real historical conversation through SQLite's read-only mode; render a copy.
 const historical=JSON.parse(execFileSync(path.join(root,'runtimes/downloader/bin/python'),['-c',"import sqlite3,json; c=sqlite3.connect('file:workspace/PrimaryMN/metadata/research.sqlite3?mode=ro',uri=True); print(c.execute('select data from chat_threads where archived=0 order by created desc limit 1').fetchone()[0])"],{cwd:root,encoding:'utf8'}));
 await page.evaluate(messages=>{window.thread.messages=messages;window.show('chat');},historical);
 const count=historical.reduce((n,m)=>n+(m.result?.queries?.length||0),0);await expect(page.getByRole('button',{name:/复制检索式：/})).toHaveCount(count);
 await page.locator('.chat-message.assistant').last().locator('.chat-proposal-action').first().scrollIntoViewIfNeeded();
 await mkdir(path.join(root,'docs/search-fixes-20260929'),{recursive:true});await page.screenshot({path:path.join(root,'docs/search-fixes-20260929/'+(useWebkit?'webkit':'chromium')+'-followup.png')});
 expect(errors).toEqual([]);console.log('PrimaryMN historical queries with inline controls: '+count);console.log('PASS: historical/streaming inline query controls, incomplete fence guard, wheel/drag pause and explicit resume, stable historical/live click targets, independent save/retry, coalesced long reasoning and final-tail preservation, pending-only batch, current/delay/single cancellation, no console errors');
}catch(error){console.error(error);throw error;}finally{await browser?.close();await server?.close();await rm(tmp,{recursive:true,force:true});}
