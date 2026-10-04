import {chromium,webkit,expect} from '@playwright/test';
import {readFile,writeFile,mkdir,mkdtemp,symlink} from 'node:fs/promises';
import {spawn,execFileSync} from 'node:child_process';
import path from 'node:path';
import ts from 'typescript';
const root=process.cwd(),testRoot=await mkdtemp(path.join(root,'tmp/retry-ui-'));
for(const folder of ['services','runtimes'])await symlink(path.join(root,folder),path.join(testRoot,folder));
const env={...process.env,SCHOLARNOTELM_ROOT:testRoot,PYTHONDONTWRITEBYTECODE:'1'};
function rpc(action,args={}){const out=JSON.parse(execFileSync(path.join(root,'cache/tauri-target/debug/research-cli'),[],{env,input:JSON.stringify({action,args}),encoding:'utf8'}));if(!out.ok)throw Error(out.error);return out.data;}
rpc('storage.initialize');rpc('mesh.settings',{autoUpdate:false,includeScr:false});rpc('download.settings.save',{enhanced:false,fastOa:false,mirrors:[]});
const code=ts.transpileModule(await readFile('apps/desktop/src/data.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {seedState}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const project={...seedState.projects[1],id:'retrytest',name:'下载补救验证',papers:[],tasks:[],messages:[]};
rpc('storage.register',{project:project.id,folder:'RetryTest',data:project});rpc('storage.state.write',{state:{...seedState,active:project.id,projects:[project]}});
const xml='<PubmedArticleSet>'+[123,124,126].map(id=>`<PubmedArticle><MedlineCitation><PMID>${id}</PMID><Article><ArticleTitle>补救验证文献 ${id}</ArticleTitle><Abstract><AbstractText>Fixture abstract</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/${id}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>`).join('')+'</PubmedArticleSet>';
rpc('xml.import',{project:project.id,name:'fixture.xml',xml});
execFileSync(path.join(root,'runtimes/downloader/bin/python'),['-c',`
import sys,os,json,io
sys.path.insert(0,os.path.join(os.getcwd(),'services/downloader'))
import engine as e
from pypdf import PdfWriter
e.PROJECT='retrytest'
e.launch=lambda:None
b=e.create({'project':'retrytest','papers':[{'pmid':str(p),'doi':'10.1/'+str(p),'title':'补救验证文献 '+str(p)} for p in [123,124,125]]})
for p in ['123','124','125']:
 e.execute("INSERT INTO attempts(batch,pmid,stage,outcome,elapsed,detail) VALUES(?,?,'scihub_bloom','failed',0,'{}')",(b['id'],p))
e.execute("UPDATE items SET state='failed'");e.execute("UPDATE batches SET state='done'")
buf=io.BytesIO();w=PdfWriter();w.add_blank_page(width=100,height=100);w.write(buf)
p=e.paper_dir('retrytest','124')/'124.pdf';p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(buf.getvalue())
`],{env,cwd:root});
const vite=spawn(path.join(root,'runtimes/node/bin/node'),['node_modules/vite/bin/vite.js','--config','apps/desktop/vite.config.ts','--port','1437'],{cwd:root,env,stdio:'ignore'});
const kind=process.env.UI_BROWSER||'chromium',browser=await(kind==='webkit'?webkit:chromium).launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:950}});page.setDefaultTimeout(20000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
let mockWaiting=false;
await page.route('**/__research',async route=>{
 const req=route.request().postDataJSON();
 if(mockWaiting&&req.action==='download.list'){
  const state=rpc('download.list',{project:project.id});const b=state.batches[0];
  b.state='running';b.counts={running:1};b.items[0].state='running';b.items[0].stage='scihub_retry';b.items[0].error='';b.items[0].progress={bloomHit:true,retryStatus:'waiting',nextAttemptAt:Date.now()/1000+30,retryUsed:1};
  b.bloomSummary={hits:1,firstSuccess:0,otherRecovery:0,retrySuccess:0,failed:0,pending:1};
  return route.fulfill({json:{ok:true,data:state}});
 }
 await route.continue();
});
try{
 for(let i=0;i<60;i++){try{if((await fetch('http://127.0.0.1:1437')).ok)break;}catch{}await new Promise(r=>setTimeout(r,200));}
 await page.goto('http://127.0.0.1:1437');await page.getByRole('button',{name:'任务中心',exact:true}).click();
 const retry=page.getByRole('button',{name:'重试 Bloom 命中未完成项',exact:true});await expect(retry).toBeEnabled();await retry.click();
 await expect(page.locator('.toast')).toContainText('已创建 Bloom 补救任务 · 1 篇');
 await expect(page.locator('.download-batch').first()).toContainText('PDF 下载 · 1 篇');
 await expect(page.locator('.download-batch').first()).toContainText('已完成');
 const state=rpc('download.list',{project:project.id});expect(state.batches[0].items.map(i=>i.pmid)).toEqual(['123']);
 await page.getByRole('button',{name:'逐篇详情',exact:true}).first().click();await expect(page.locator('.download-item').first()).toContainText('补救未成功');
 await page.getByRole('button',{name:'查看报告',exact:true}).first().click();await expect(page.locator('.download-report')).toContainText('Bloom Recovery Summary');await expect(page.locator('.download-report')).toContainText('Sci-Hub: fixed workers');await page.getByRole('button',{name:'关闭弹窗',exact:true}).click();
 execFileSync(path.join(root,'runtimes/downloader/bin/python'),['-c',`
import os,sys,json
sys.path.insert(0,os.path.join(os.getcwd(),'services/downloader'))
import engine as e
e.PROJECT='retrytest'
b=e.one('SELECT id FROM batches ORDER BY created DESC LIMIT 1')['id']
e.execute("UPDATE items SET state='deferred',error='已延期：尚未发出本阶段请求' WHERE batch=?",(b,))
p=e.progress(b,'123');p['retryStatus']='deferred';e.save_progress(b,'123',p)
`],{env,cwd:root});
 await page.evaluate(()=>window.dispatchEvent(new Event('downloads-changed')));await expect(page.locator('.download-item').first()).toContainText('已延期，待重试');await expect(page.locator('.download-batch').first()).toContainText('已延期');
 await page.locator('.download-batch').first().getByRole('button',{name:'重试失败 / 延期项',exact:true}).click();
 await expect(page.locator('.download-item').first()).toContainText('未获取全文');
 mockWaiting=true;await page.evaluate(()=>window.dispatchEvent(new Event('downloads-changed')));await expect(page.locator('.download-item').first()).toContainText('等待补救');await expect(retry).toBeDisabled();await expect(page.locator('.download-item').first()).toContainText('已发出 1 次');
 await page.screenshot({path:`docs/screenshots/retry-tasks-${kind}.png`,fullPage:true});
 await page.getByRole('button',{name:'切换主题',exact:true}).click();await page.setViewportSize({width:1000,height:720});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:`docs/screenshots/retry-tasks-dark-${kind}.png`,fullPage:true});
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'PDF 下载',exact:true}).click();await expect(page.locator('.download-settings')).toContainText('HTTP 累计上限 75 秒');await expect(page.getByRole('checkbox',{name:'启用 OA 慢速补救与 Europe PMC 深度回退'})).not.toBeChecked();
 await expect(page.locator('.download-route')).toHaveText('PMC S3 → 历史来源 / Sci-Hub → Unpaywall → Sci-Hub 补救 / 重试');
 await page.getByText('并发与请求参数',{exact:true}).click();
 await expect(page.getByLabel('OA 单文件总时限 · 秒',{exact:true})).toHaveValue('45');
 await expect(page.getByLabel('OA 单篇总时限 · 秒',{exact:true})).toHaveValue('60');
 await page.getByLabel('OA 单文件总时限 · 秒',{exact:true}).fill('50');
 await page.getByRole('button',{name:'保存下载配置',exact:true}).click();
 await expect(page.locator('.wb-success')).toContainText('下载配置已保存');
 expect(rpc('download.settings').oaFileTimeout).toBe(50);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:`docs/screenshots/s3-first-settings-${kind}.png`,fullPage:true});
 expect(errors).toEqual([]);await writeFile(`docs/RETRY_UI_${kind.toUpperCase()}.json`,JSON.stringify({passed:true,fixture:testRoot,checks:['real RPC manual retry filters current corpus, skips valid PDF and nonhit','bounded recovery report','waiting status, request count, active-batch button guard (UI fixture)','light and dark at 1440 and 1000px','enhanced remains opt-in'],errors},null,2));console.log('Retry UI passed: '+kind);
}finally{await browser.close();vite.kill();}
