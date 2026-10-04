/** Isolated mock workspace: no network calls, project mutations or paid jobs. */
import {chromium,webkit,expect} from '@playwright/test';
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises';
import path from 'node:path';
const root=process.cwd(),tmp=await mkdtemp(path.join(root,'tmp/bulk-filters-ui-')),out=path.join(root,'docs/unified-filters-20260929');let server,browser;
try{
 await mkdir(out,{recursive:true});
 await writeFile(path.join(tmp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
 await writeFile(path.join(tmp,'main.jsx'),`import React from 'react';import {createRoot} from 'react-dom/client';import Workbench from '/@fs/${root}/apps/desktop/src/SearchWorkbench.tsx';import Workflow from '/@fs/${root}/apps/desktop/src/LiteratureWorkflow.tsx';import '/@fs/${root}/apps/desktop/src/styles.css';import '/@fs/${root}/apps/desktop/src/workbench.css';import '/@fs/${root}/apps/desktop/src/conversation.css';import '/@fs/${root}/apps/desktop/src/panels.css';
window.calls=[];window.notices=[];
const filters={start:'',end:'',sort:'relevance',mode:'explore',limit:30,jcr:false,quartiles:[],unknown:'keep'};
const query=(id,props={})=>({id,name:id,text:id+'[tiab]',source:'manual',enabled:true,archived:false,revision:1,error:'',filters:{...filters},...props});
window.data={queries:[query('策略 A',{filters:{...filters,limit:77}}),query('策略 B'),query('已停用',{enabled:false}),query('已归档',{archived:true}),query('导入 XML',{source:'import'}),query('Zotero 来源',{source:'zotero'})],corpus:{papers:[],included:0,snapshot:'fixture'}};
const originalFetch=window.fetch.bind(window);window.fetch=async(url,opts)=>{if(!String(url).startsWith('/__research'))return originalFetch(url,opts);const {action,args}=JSON.parse(opts.body);window.calls.push({action,args});let result={};
if(action==='workspace')result=window.data;
else if(action==='query.filters.apply'){if(window.failBatch)return new Response(JSON.stringify({ok:false,error:'模拟批量保存失败'}));for(const q of window.data.queries.filter(q=>!q.archived&&q.source!=='zotero')){if(args.dates&&q.source!=='import'){Object.assign(q.filters,args.dates);q.revision++;q.stale=true;}if(args.jcr)Object.assign(q.filters,args.jcr);}result=window.data;}
else if(action==='query.save'){Object.assign(window.data.queries.find(q=>q.id===args.id),args);result=window.data;}
else if(!['download.start','markdown.start','vector.start','markdown.reconcile','markdown.folder'].includes(action))throw Error('Unexpected RPC '+action);
return new Response(JSON.stringify({ok:true,data:structuredClone(result)}));};
const tree=createRoot(document.getElementById('root'));window.show=mode=>tree.render(<div className="main-content" style={{marginLeft:260}}>{mode==='workflow'?<div className="page library-page"><Workflow total={10} downloads={{batches:[],assets:{}}} markdown={{pdfCount:5,latestCount:2,ready:true,items:[{pdf:true,raw:true}],files:{}}} vectors={{configured:true,readyDocuments:2}} error="" vectorError=""/></div>:<Workbench/>}</div>);window.show('queries');`);
 server=await createServer({configFile:false,root:tmp,cacheDir:path.join(tmp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','@tauri-apps/api/core','react-markdown','remark-gfm']},server:{host:'127.0.0.1',port:0,fs:{allow:[root]}},plugins:[{name:'mocks',enforce:'pre',resolveId(src,importer){if(importer?.startsWith(root+'/apps/desktop/src/')&&['./context','./download-api','./Vector','./ProjectStorage','./useQuery'].includes(src))return '\0'+src;},load(id){if(id==='\0./context')return `export const useApp=()=>({project:{id:'test',name:'测试项目',papers:[]},notify:t=>window.notices.push(t),setPage:()=>{},openSettings:()=>{}});`;if(id==='\0./download-api')return 'export const useDownloads=()=>({data:{batches:[],assets:{}}});export const startDownload=async()=>({count:0});export const downloadChanged=()=>{};';if(id==='\0./Vector')return 'export const ChunkBrowser=()=>null;export const IndexProgress=()=>null;';if(id==='\0./ProjectStorage')return 'export const ProjectFilesActions=()=>null;';if(id==='\0./useQuery')return 'export const useQuery=action=>({data:action==="zotero.status"?null:{job:null}});';}}]});await server.listen();
 const engine=process.env.UI_BROWSER==='webkit'?'webkit':'chromium';browser=await (engine==='webkit'?webkit:chromium).launch({headless:true,...(engine==='webkit'?{}:{channel:'chrome'})});const page=await browser.newPage({viewport:{width:1512,height:982}}),errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());await page.goto(`http://127.0.0.1:${server.httpServer.address().port}`);
 const open=()=>page.getByRole('button',{name:'统一 JCR / 日期'}).click();await open();let dialog=page.getByRole('dialog');
 await expect(dialog).toContainText('4 条未归档');await dialog.getByLabel('发表日期 · 开始').fill('2020-01-01');await dialog.getByLabel('发表日期 · 结束').fill('2026-09-29');await dialog.getByLabel('Q1',{exact:true}).check();
 await page.screenshot({path:path.join(out,`${engine}-bulk.png`)});
 await dialog.getByRole('button',{name:'应用到全部检索式'}).click();await expect(dialog).toHaveCount(0);
 const data=await page.evaluate(()=>window.data.queries);expect(data.find(q=>q.id==='策略 A').filters.limit).toBe(77);expect(data.find(q=>q.id==='策略 B').filters.quartiles).toEqual(['Q1']);expect(data.find(q=>q.id==='已停用').filters.start).toBe('2020-01-01');expect(data.find(q=>q.id==='已归档').filters.jcr).toBe(false);expect(data.find(q=>q.id==='导入 XML').filters.start).toBe('');
 expect(data.find(q=>q.id==='Zotero 来源').filters).toMatchObject({start:'',jcr:false});
 // A per-query exception stays independent after the bulk operation.
 await page.getByRole('button',{name:'编辑 策略 A',exact:true}).click();await dialog.getByLabel('Q2',{exact:true}).check();await dialog.getByRole('button',{name:'保存修改'}).click();await expect(dialog).toHaveCount(0);
 expect(await page.evaluate(()=>window.data.queries.find(q=>q.id==='策略 A').filters.quartiles)).toEqual(['Q1','Q2']);expect(await page.evaluate(()=>window.data.queries.find(q=>q.id==='策略 B').filters.quartiles)).toEqual(['Q1']);
 // A date-only change does not erase JCR exceptions; validation and retry keep the dialog open.
 await open();await dialog.getByLabel('统一 JCR 分区',{exact:true}).uncheck();await dialog.getByLabel('发表日期 · 开始').fill('2026-09-30');await dialog.getByRole('button',{name:'应用到全部检索式'}).click();await expect(dialog.getByRole('alert')).toContainText('开始日期不能晚于结束日期');
 await dialog.getByLabel('发表日期 · 开始').fill('');await dialog.getByLabel('发表日期 · 结束').fill('');await page.evaluate(()=>{window.failBatch=true;});await dialog.getByRole('button',{name:'应用到全部检索式'}).click();await expect(dialog.getByRole('alert')).toContainText('模拟批量保存失败');await page.evaluate(()=>{window.failBatch=false;});await dialog.getByRole('button',{name:'应用到全部检索式'}).click();await expect(dialog).toHaveCount(0);expect(await page.evaluate(()=>window.data.queries.find(q=>q.id==='策略 A').filters.quartiles)).toEqual(['Q1','Q2']);
 await open();await dialog.getByLabel('统一日期',{exact:true}).uncheck();await dialog.getByLabel('统一 JCR 分区',{exact:true}).uncheck();await expect(dialog.getByRole('button',{name:'应用到全部检索式'})).toBeDisabled();await dialog.getByRole('button',{name:'取消',exact:true}).click();
 if(process.env.BULK_ONLY==='1'){expect(errors).toEqual([]);console.log('PASS: bulk filter application, validation, per-query overrides, and Zotero exclusion');}else{
 await page.evaluate(()=>window.show('workflow'));
 const actions=[['下载','download.start'],['转换全文','markdown.start'],['建立 / 更新','vector.start']];
 for(const width of [1512,1232,1000,800]){
  await page.setViewportSize({width,height:982});
  for(const [name,action] of actions){
   const button=page.getByRole('button',{name,exact:true});await expect(button).toBeEnabled();await button.scrollIntoViewIfNeeded();
   // Every sampled point inside the visible button must hit that exact button, not a sibling menu.
   expect(await button.evaluate(el=>{const r=el.getBoundingClientRect();return [.05,.5,.95].flatMap(x=>[.1,.5,.9].map(y=>el.contains(document.elementFromPoint(r.x+r.width*x,r.y+r.height*y))));})).toEqual(Array(9).fill(true));
   for(const point of [[.05,.5],[.5,.5],[.95,.9]]){const count=await page.evaluate(action=>window.calls.filter(c=>c.action===action).length,action);const r=await button.boundingBox();await page.mouse.click(r.x+r.width*point[0],r.y+r.height*point[1]);await expect.poll(()=>page.evaluate(action=>window.calls.filter(c=>c.action===action).length,action)).toBe(count+1);await expect(button).toBeEnabled();}
  }
 }
 const pdf=page.locator('.workflow-summary>div').nth(1);
 for(const width of [1512,1232,1000,800]){
  await page.setViewportSize({width,height:982});
  const before=await pdf.getByRole('button',{name:'下载',exact:true}).boundingBox();
  await pdf.getByRole('button',{name:'PDF 操作',exact:true}).click();const menu=page.getByRole('menu',{name:'PDF 操作'});await expect(menu).toBeVisible();
  expect(await pdf.getByRole('button',{name:'下载',exact:true}).boundingBox()).toEqual(before);
  const bounds=await menu.boundingBox(),trigger=await pdf.getByRole('button',{name:'PDF 操作',exact:true}).boundingBox();
  await expect.poll(async()=>{const m=await menu.boundingBox(),t=await pdf.getByRole('button',{name:'PDF 操作',exact:true}).boundingBox();return Math.abs(m.x+m.width-t.x-t.width);}).toBeLessThan(2);
  expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(width);
  const buttons=await menu.getByRole('menuitem').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return {x:r.x,width:r.width,height:r.height};}));
  expect(buttons).toHaveLength(4);expect(new Set(buttons.map(b=>b.x)).size).toBe(1);expect(new Set(buttons.map(b=>b.width)).size).toBe(1);expect(buttons.every(b=>b.height>=35.99)).toBe(true);
  const hits=await menu.getByRole('menuitem').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height-3));}));
  if(hits.some(hit=>!hit)){console.log(await menu.evaluate(el=>({popover:el.matches(':popover-open'),attr:el.getAttribute('popover'),css:el.getAttribute('style'),rect:el.getBoundingClientRect().toJSON(),outer:el.outerHTML,hit:document.elementFromPoint(el.getBoundingClientRect().x+50,el.getBoundingClientRect().bottom-10)?.outerHTML})));await page.screenshot({path:path.join(out,`${engine}-menu-failure.png`)});}
  expect(hits).toEqual([true,true,true,true]);
  const normal=await menu.getByRole('menuitem',{name:'检查本地文件'}).evaluate(el=>getComputedStyle(el).color);const danger=await menu.locator('button.danger').evaluate(el=>getComputedStyle(el).color);expect(danger).not.toBe(normal);
  await page.screenshot({path:path.join(out,`${engine}-pdf-menu-${width}.png`),animations:'disabled'});
  const count=await page.evaluate(()=>window.calls.filter(c=>c.action==='markdown.reconcile').length);
  await menu.getByRole('menuitem',{name:'检查本地文件'}).click();
  await expect.poll(()=>page.evaluate(()=>window.calls.filter(c=>c.action==='markdown.reconcile').length)).toBe(count+1);
  await expect(page.getByRole('menu',{name:'PDF 操作'})).toHaveCount(0);
 }
 await pdf.getByRole('button',{name:'PDF 操作',exact:true}).focus();await page.keyboard.press('Enter');await expect(page.getByRole('menu',{name:'PDF 操作'})).toBeVisible();await page.keyboard.press('Escape');await expect(page.getByRole('menu',{name:'PDF 操作'})).toHaveCount(0);await expect(pdf.getByRole('button',{name:'PDF 操作',exact:true})).toBeFocused();
 await pdf.getByRole('button',{name:'PDF 操作',exact:true}).click();await page.getByRole('button',{name:'下载',exact:true}).click();await expect(page.getByRole('menu',{name:'PDF 操作'})).toHaveCount(0);
 await page.screenshot({path:path.join(out,`${engine}-workflow.png`)});expect(errors).toEqual([]);console.log(`${engine}: PASS bulk filter apply, per-query override, date-only preservation, validation/retry, all 9 hit points and edge/center clicks at 4 widths, more menu, no console errors`);
}}finally{await browser?.close();await server?.close();await rm(tmp,{recursive:true,force:true});}
