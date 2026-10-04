/** White-screen and Zotero entry regression; isolated mocked RPC, no real project writes. */
import {chromium,webkit,expect} from '@playwright/test';
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises';
import path from 'node:path';
const root=process.cwd(),tmp=await mkdtemp(path.join(root,'tmp/library-details-')),out=path.join(root,'docs/gui-copy-20261002/library');let server,browser;
try{
 await mkdir(out,{recursive:true});
 await writeFile(path.join(tmp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
 await writeFile(path.join(tmp,'main.jsx'),`import React from 'react';import {createRoot} from 'react-dom/client';
import Library from '/@fs/${root}/apps/desktop/src/Library.tsx';
import '/@fs/${root}/apps/desktop/src/styles.css';import '/@fs/${root}/apps/desktop/src/workbench.css';import '/@fs/${root}/apps/desktop/src/panels.css';
window.calls=[];window.project={id:'primary',name:'原发性膜性肾病',papers:Array.from({length:5},(_,i)=>({id:'PMID-'+(i+1),researchManaged:true,title:['Sci-Hub 文献：对象格式的身份校验','历史文献：文字格式的身份校验','PMC 文献：无身份记录','未来格式文献','等待补充全文的文献'][i],author:'Test Author',year:2024,journal:'Research Journal',tag:'PubMed',status:'abstract',starred:false,abstract:'此处为隔离测试文献的摘要。'}))};
const identities=[{status:'match',reason:'doi_in_frontmatter',sha256:'abc',fileValid:true},'历史校验说明',undefined,{status:'future',reason:'new_reason',extra:{value:1}}];
const assets=Object.fromEntries(identities.map((identity,i)=>[String(i+1),{pmid:String(i+1),path:'mock/'+(i+1)+'.pdf',source:i<2?'Sci-Hub':'PMC S3',bytes:50000,pages:5,sha256:'abc',exists:true,identity}]));
const markdown={ready:true,pdfCount:4,markdownCount:0,latestCount:0,abstractCount:0,files:{redundant:0,errors:[]},items:window.project.papers.map((p,i)=>({pmid:String(i+1),pdf:i<4,pdfState:i<4?'latest':'missing',markdownState:'missing',needsConversion:i<4})),job:null};
window.fetch=async(url,opts)=>{if(url!=='/__research')throw Error('Unexpected request '+url);const {action,args}=JSON.parse(opts.body);window.calls.push({action,args});let data;
if(action==='download.list')data={batches:[],assets};
else if(action==='markdown.status')data=markdown;
else if((action==='vector.status'||action==='vector.progress'))data={configured:true,readyDocuments:0,eligibleDocuments:5,documents:5,chunks:0,readyChunks:0,metadataPending:0,items:[],job:null};
else if(action==='library.status')data={job:null};
else if(action==='download.start')data={id:'local-only',count:args.pmids.length};
else throw Error('Unexpected RPC '+action);
return new Response(JSON.stringify({ok:true,data}));};
createRoot(document.getElementById('root')).render(<main className="main-content"><Library/></main>);`);
 server=await createServer({configFile:false,root:tmp,cacheDir:path.join(tmp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','@tauri-apps/api/core']},server:{host:'127.0.0.1',port:0,fs:{allow:[root]}},plugins:[{name:'mock-context',enforce:'pre',resolveId(src,importer){if(importer?.startsWith(root+'/apps/desktop/src/')&&src==='./context')return '\0test-context';},load(id){if(id==='\0test-context')return `export const useApp=()=>({project:window.project,notify:x=>{window.notice=x},setPage:()=>{},openSettings:()=>{},updateProject:()=>{},openPaper:p=>{window.reader=p.id}});`;}}]});await server.listen();
 const engine=process.env.UI_BROWSER==='webkit'?'webkit':'chromium';browser=await (engine==='webkit'?webkit:chromium).launch({headless:true,...(engine==='chromium'?{channel:'chrome'}:{})});const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());await page.goto(`http://127.0.0.1:${server.httpServer.address().port}`);
 const titles=page.locator('.paper-title');await expect(titles).toHaveCount(5);
 await expect(page.locator('.workflow-summary>div').nth(1)).toContainText('1 篇待下载处理');
 const expectations=['正文 DOI 与目标文献一致','历史校验说明','PMC S3','正文身份校验结果已记录'];
 for(let i=0;i<4;i++){
  await titles.nth(i).click();const modal=page.getByRole('dialog');await expect(modal).toBeVisible();await expect(modal).toContainText(expectations[i]);
  if(i===0)await page.screenshot({path:path.join(out,engine+'-article-details.png'),animations:'disabled'});
  await page.getByRole('button',{name:'关闭弹窗'}).click();await expect(titles).toHaveCount(5);
 }
 await titles.nth(4).click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'打开阅读器'}).click();expect(await page.evaluate(()=>window.reader)).toBe('PMID-5');
 await page.getByRole('button',{name:'PDF 操作',exact:true}).click();const menu=page.getByRole('menu',{name:'PDF 操作'});await expect(menu.getByRole('menuitem',{name:'从 Zotero 导入'})).toBeEnabled();await page.screenshot({path:path.join(out,engine+'-zotero-menu.png'),animations:'disabled'});
 await menu.getByRole('menuitem',{name:'从 Zotero 导入'}).click();await expect(menu).toHaveCount(0);
 await expect.poll(()=>page.evaluate(()=>window.calls.filter(c=>c.action==='download.start').map(c=>c.args))).toEqual([{project:'primary',mode:'zotero',pmids:['5']}]);
 expect(errors).toEqual([]);console.log(JSON.stringify({passed:true,browser:engine,checks:['actual Library click opens details for object/string/missing/future identities','close and reopen remain interactive','reader action works','Zotero menu runs only missing PDFs with isolated mode','no browser errors']}));
}finally{await browser?.close();await server?.close();await rm(tmp,{recursive:true,force:true});}
