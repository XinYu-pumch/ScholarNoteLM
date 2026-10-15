/** Fully isolated UI fixture. No bridge, user projects, credentials or model calls. */
import {chromium,expect} from '@playwright/test';
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises';
import path from 'node:path';
const root=process.cwd(),temp=await mkdtemp(path.join(root,'tmp/review-stages-ui-'));
let server,browser;
try {
 await writeFile(path.join(temp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
 await writeFile(path.join(temp,'main.jsx'),`import React from 'react';import {createRoot} from 'react-dom/client';
import Review from '/@fs/${root}/apps/desktop/src/Review.tsx';
import '/@fs/${root}/apps/desktop/src/styles.css';import '/@fs/${root}/apps/desktop/src/design.css';
import {invalidate} from '/@fs/${root}/apps/desktop/src/query-cache.ts';
import {configureLocale,useLocale} from '/@fs/${root}/apps/desktop/src/i18n.ts';
configureLocale('zh');window.language=configureLocale;
window.calls=[];window.refresh=()=>invalidate('test',['review.writing.status','review.writing.activity']);
const rows=Array.from({length:105},(_,i)=>({id:(i+1).toString(16).padStart(32,'0'),serial:String(i+1),title:'Autoantibodies and podocyte injury in primary membranous nephropathy '+(i+1)}));
const names=['Pathogenesis_of_primary_membranous_nephropathy_jinaV4','Comparison_workspace'];
const works=names.map(name=>({name,description:'Pathogenesis of primary membranous nephropathy',contentLanguage:'en',schema:2,created:1,materialModel:'jina-embeddings-v4'}));
const config={concurrency:20,topK:7,language:'English',requirements:'',profileId:'',model:'deepseek-flash',contextChars:90000,limitContext:false};
const initial=()=>({config,rows,units:rows.map(r=>({...r,nodes:[r.id],leafIds:[r.id],state:'pending',latest:false,promptReady:false,hasContent:false,error:'',revision:'1'})),job:{},latest:0,total:105,prepared:0,currentOutlineCount:105,hasContent:false,manuscriptCount:0,draftCount:1,fileRevision:'1',model:'deepseek-flash',runtimeReady:true,retrieval:{config:{method:'api'},apiModel:'Jina v4',apiVerified:true},stages:{preparation:{state:'idle',completed:0,total:105},writing:{state:'idle',completed:0,total:105}}});
window.states=Object.fromEntries(names.map(n=>[n,initial()]));window.primary=names[0];
window.progress=(phase,count,jobState)=>{const d=window.states[names[0]];d.job={mode:phase,state:jobState,total:105-count,completed:0,settled:0};d.fileRevision=String(Math.random());
 if(phase==='prepare'){d.prepared=count;d.stages.preparation={state:count===105?'ready':'partial',completed:count,total:105};d.units.forEach((u,i)=>u.promptReady=i<count);}
 else{d.latest=count;d.hasContent=count>0;d.stages.writing={state:count===105?'complete':'partial',completed:count,total:105};d.units.forEach((u,i)=>{u.latest=i<count;u.hasContent=i<count;u.state=i<count?'latest':'pending';});}
 window.refresh();};
const detail=name=>({workspace:works.find(w=>w.name===name),version:{id:'current',revision:1,state:'done',topic:'Pathogenesis of primary membranous nephropathy',requirements:'',error:''},rows,csv:'',csvError:'',hasOriginal:true,response:''});
const native=window.fetch.bind(window);window.fetch=async(url,options)=>{if(!String(url).startsWith('/__research'))return native(url,options);const {action,args}=JSON.parse(options.body);window.calls.push({action,args});let data;const d=window.states[args.name];
 switch(action){
 case 'profile.list':data={activeProfile:'fixture',profiles:[{id:'fixture',name:'Fixture',model:'deepseek-flash',models:['deepseek-flash']}]};break;
 case 'review.list':data={workspaces:works,model:'deepseek-flash',source:{total:111,abstractCount:111}};break;
 case 'review.get':data=detail(args.name);break;
 case 'review.describe':{const w=works.find(w=>w.name===args.name);w.name=args.newName;w.description=args.description;window.states[w.name]=d;data=w;break;}
 case 'review.writing.export':data={path:'fixture/review.'+args.format,partial:d.latest<d.total};break;
 case 'review.writing.activity':data={state:d.job.state||'idle'};break;
 case 'review.writing.status':data=d;break;
 case 'review.writing.section':data={sections:d.latest?[{node_id:args.nodeId,markdown:'Evidence-supported review text.'}]:[],evidence:{}};break;
 case 'review.writing.prepare':case 'review.writing.prepare.resume':data=d;d.job={state:'running',mode:'prepare',total:105-d.prepared};break;
 case 'review.writing.start':data=d;d.job={state:'running',mode:'write',total:105-d.latest};break;
 case 'review.writing.cancel':data=d;d.job.state='cancelled';d.stages[d.job.mode==='prepare'?'preparation':'writing'].state='partial';break;
 case 'review.writing.manuscripts':data=args.drafts?[{id:'d'.repeat(64),created:1,label:'Draft',topic:'Old incomplete draft',partial:true}]:[];break;
 case 'review.writing.manuscript':case 'review.writing.preview':data={markdown:'Draft preview',displayBlocks:[]};break;
 default:throw Error('Unexpected RPC '+action);
 }return new Response(JSON.stringify({ok:true,data:structuredClone(data)}),{headers:{'Content-Type':'application/json'}});};
function App(){useLocale();return <main className="main-content page-review" style={{height:'100vh',padding:0}}><Review/></main>;}createRoot(document.getElementById('root')).render(<App/>);`);
 server=await createServer({configFile:false,root:temp,cacheDir:path.join(temp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','@tauri-apps/api/core','react-markdown','remark-gfm']},server:{host:'127.0.0.1',port:0,fs:{allow:[root]}},plugins:[{name:'isolated-context',enforce:'pre',resolveId(src,importer){if(importer?.startsWith(root+'/apps/desktop/src/')&&src==='./context')return '\0fixture-context';},load(id){if(id==='\0fixture-context')return `export const useApp=()=>({notify:()=>{},openSettings:()=>{},state:{defaultContentLanguage:'zh'},project:{id:'test',name:'Test',papers:[]}});`;}}]});await server.listen();
 browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1500,height:1000}});page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
 await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
 await page.goto(`http://127.0.0.1:${server.httpServer.address().port}`);console.log('loaded');await page.getByRole('tab',{name:'综述撰写'}).click();
 const prepare=page.getByRole('button',{name:'准备写作材料',exact:true}),write=page.getByRole('button',{name:'撰写综述',exact:true});
 await expect(prepare).toBeEnabled();await expect(write).toBeDisabled();
 const a=await prepare.boundingBox(),b=await write.boundingBox();expect(b.x).toBeGreaterThan(a.x+a.width);expect(Math.abs(a.y-b.y)).toBeLessThan(2);
 await expect(page.getByText('本组章节一起撰写：',{exact:false})).toHaveCount(0);
 await prepare.click();const stop=page.getByRole('button',{name:'停止准备',exact:true});await expect(stop).toBeEnabled();await stop.hover();await expect(stop.locator('.stage-stop-label')).toBeVisible();
 await page.evaluate(()=>window.progress('prepare',80,'running'));
 await expect(page.getByRole('progressbar',{name:'材料准备进度'})).toHaveAttribute('value','80');
 await stop.click();await expect(page.getByRole('button',{name:'重试失败项',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:/Comparison workspace/}).click();await expect(page.getByRole('button',{name:'准备写作材料',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:/Pathogenesis of primary membranous nephropathy jinaV4/}).click();await expect(page.getByRole('button',{name:'重试失败项',exact:true})).toBeEnabled();
 await page.evaluate(()=>window.progress('prepare',105,'done'));await expect(page.getByRole('button',{name:'写作材料就绪'})).toBeDisabled();await expect(write).toBeEnabled();
 await write.click();await expect(page.getByRole('button',{name:'停止撰写'})).toBeEnabled();
 await page.evaluate(()=>window.progress('write',80,'partial'));await expect(page.getByRole('progressbar',{name:'全文完成度'})).toHaveAttribute('value','80');
 await page.getByRole('button',{name:'重试失败项',exact:true}).click();await expect(page.getByRole('progressbar',{name:'全文完成度'})).toHaveAttribute('value','80');
 // Switching workspaces leaves the worker running, and returning restores its stop action.
 await page.getByRole('button',{name:/Comparison workspace/}).click();await page.getByRole('button',{name:/Pathogenesis of primary membranous nephropathy jinaV4/}).click();await expect(page.getByRole('button',{name:'停止撰写'})).toBeEnabled();
 // Export and preview work while the review is incomplete.
 await page.evaluate(()=>window.progress('write',80,'partial'));
 const preview=page.getByRole('button',{name:'全文预览',exact:true});await preview.click();await expect(preview).toHaveAttribute('aria-pressed','true');await expect(page.getByRole('heading',{name:'完整综述预览'})).toBeVisible();
 await preview.click();await expect(preview).toHaveAttribute('aria-pressed','false');await expect(page.getByRole('heading',{name:'完整综述预览'})).toHaveCount(0);
 await page.getByRole('button',{name:'导出综述'}).click();await page.getByRole('menuitem',{name:'Markdown',exact:true}).click();
 expect(await page.evaluate(()=>window.calls.some(c=>c.action==='review.writing.export'&&c.args.format==='md'))).toBeTruthy();
 await expect(page.getByRole('button',{name:'导出综述'})).toContainText('导出');await expect(page.getByText('导出草稿',{exact:true})).toHaveCount(0);
 await expect(page.locator('.writing-batch-progress,.writing-material-source,.writing-settings-summary')).toHaveCount(0);
 const progressStyle=await page.locator('.writing-stage-progress').evaluateAll(rows=>rows.map(row=>({font:getComputedStyle(row).fontSize,left:row.querySelector('progress').getBoundingClientRect().left,height:row.querySelector('progress').getBoundingClientRect().height,width:row.querySelector('progress').getBoundingClientRect().width})));expect(progressStyle[0]).toEqual(progressStyle[1]);
 await page.getByRole('button',{name:'撰写设置',exact:true}).click();const settings=page.getByRole('dialog',{name:'撰写设置'});
 await expect(settings.getByText('综述语言',{exact:true})).toHaveCount(0);await expect(settings.getByText('材料检索',{exact:true})).toHaveCount(0);
 await expect(settings.getByLabel('正文额外要求')).not.toBeVisible();await settings.locator('summary').filter({hasText:'高级设置'}).click();await expect(settings.getByLabel('正文额外要求')).toBeVisible();
 const concurrency=await settings.getByRole('spinbutton',{name:'撰写并发数'}).boundingBox(),topK=await settings.getByRole('spinbutton',{name:'每节参考片段数'}).boundingBox();expect(Math.abs(concurrency.y-topK.y)).toBeLessThan(2);expect(topK.x).toBeGreaterThan(concurrency.x);
 await page.keyboard.press('Escape');
 // Context actions target the clicked workspace, including a nonselected one.
 const other=page.getByRole('button',{name:/Comparison workspace/});await other.click({button:'right'});await page.getByRole('menuitem',{name:'名称与描述',exact:true}).click();
 const rename=page.getByRole('dialog',{name:'名称与描述'});await expect(rename.getByRole('textbox',{name:'综述工作区名称'})).toHaveValue('Comparison_workspace');await rename.getByRole('textbox',{name:'综述工作区描述'}).fill('Updated comparison description');await rename.getByRole('button',{name:'保存',exact:true}).click();
 await expect(page.locator('.review-workspace-item[aria-current="page"]')).toContainText('Pathogenesis');
 await other.focus();await page.keyboard.press('Shift+F10');await expect(page.getByRole('menu',{name:'工作区更多操作'})).toBeVisible();await page.keyboard.press('Escape');await expect(other).toBeFocused();
 const create=await page.getByRole('button',{name:'新建综述工作区',exact:true}).boundingBox(),del=await page.getByRole('button',{name:'删除综述工作区',exact:true}).boundingBox();expect(del.y).toBeGreaterThan(create.y);
 await page.getByRole('button',{name:'删除综述工作区',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Pathogenesis_of_primary_membranous_nephropathy_jinaV4');await page.getByRole('button',{name:'取消',exact:true}).click();expect(await page.evaluate(()=>window.calls.some(c=>c.action==='review.delete'))).toBeFalsy();
 await page.evaluate(()=>window.progress('write',105,'done'));await expect(page.getByRole('button',{name:'综述撰写完毕'})).toBeDisabled();
 await page.getByRole('button',{name:'撰写更多操作'}).click();await page.getByRole('menuitem',{name:/历史草稿/}).click();await expect(page.getByRole('dialog',{name:'历史草稿'})).toBeVisible();await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'导出综述'}).click();await expect(page.getByRole('menu',{name:'导出综述'})).toBeVisible();await page.keyboard.press('Escape');
 if(!await page.locator('.review-workspaces').isVisible())await page.getByRole('button',{name:'展开综述工作区',exact:true}).click();
 const out=path.join(root,'docs/screenshots/review-stages');await mkdir(out,{recursive:true});await page.screenshot({path:path.join(out,'zh.png')});
 await page.evaluate(()=>window.language('en'));await expect(page.getByRole('button',{name:'Materials ready',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Review complete',exact:true})).toBeVisible();
 await page.screenshot({path:path.join(out,'en.png')});
 await page.getByRole('button',{name:'Writing settings',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();await page.screenshot({path:path.join(out,'en-settings.png')});await page.keyboard.press('Escape');
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');await expect(page.locator('.review-workspace-item').last()).toHaveCSS('color','rgb(242, 241, 238)');await page.screenshot({path:path.join(out,'en-dark.png')});await page.evaluate(()=>delete document.documentElement.dataset.theme);
 for(const width of [1100,900,720]){await page.setViewportSize({width,height:1000});if(width<1100&&await page.locator('.review-workspaces').isVisible())await page.getByRole('button',{name:'Hide review workspaces',exact:true}).first().click();
  const ready=await page.getByRole('button',{name:'Materials ready',exact:true}).boundingBox(),done=await page.getByRole('button',{name:'Review complete',exact:true}).boundingBox();expect(ready.x+ready.width).toBeLessThanOrEqual(width);expect(done.x+done.width).toBeLessThanOrEqual(width);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  const language=await page.locator('.review-content-language .content-language>span:first-child').boundingBox(),select=await page.locator('.review-content-language .app-select').boundingBox();expect(language.height).toBeLessThan(select.height);
 }
 await page.screenshot({path:path.join(out,'en-narrow.png')});
 expect(errors).toEqual([]);console.log('PASS: two stages; stop on hover; durable workspace switching; cumulative 80/105 retry; complete archive vs draft history; partial export; preview toggle; context editing and keyboard focus; delete confirmation; compact settings; matched progress; Chinese/English; responsive layout.');
}finally{await browser?.close();await server?.close();await rm(temp,{recursive:true,force:true});}
