// Real settings RPC in an isolated root; never downloads papers or contacts Zotero.
import {chromium,expect} from '@playwright/test';
import {mkdir,mkdtemp,cp,symlink,rm} from 'node:fs/promises';
import {spawn,execFileSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd(),app=await mkdtemp(path.join(root,'tmp/download-settings-ui-'));
const env={...process.env,SCHOLARNOTELM_ROOT:app};
function rpc(action,args={}){const r=JSON.parse(execFileSync(path.join(root,'cache/tauri-target/debug/research-cli'),[],{env,input:JSON.stringify({action,args:{project:'download_ui',...args}}),encoding:'utf8'}));if(!r.ok)throw Error(r.error);return r.data;}
let browser,vite;
try{
 await mkdir(path.join(app,'services'),{recursive:true});await cp(path.join(root,'services/llm_providers'),path.join(app,'services/llm_providers'),{recursive:true});await symlink(path.join(root,'services/downloader'),path.join(app,'services/downloader'));await symlink(path.join(root,'runtimes'),path.join(app,'runtimes'));await mkdir(path.join(app,'tmp'));
 const project={id:'download_ui',name:'DownloadUI',description:'Isolated fixture',color:'sage',papers:[],messages:[],sections:[],notes:{},tasks:[]};
 rpc('storage.initialize');rpc('storage.register',{folder:'DownloadUI',data:project});rpc('storage.state.write',{state:{version:1,active:project.id,theme:'light',uiLanguage:'zh',projects:[project]}});rpc('mesh.settings',{autoUpdate:false,includeScr:false});
 const defaults=rpc('download.settings');
 const requestKeys=Object.keys(defaults).filter(k=>typeof defaults[k]==='number');expect(requestKeys).toHaveLength(10);
 const custom=Object.fromEntries(requestKeys.map(k=>[k,defaults[k]+(k==='europePmcConcurrency'||k==='europePmcAttempts'?-1:1)]));
 rpc('download.settings.save',{...custom,zoteroAddress:'localhost:23120',email:'saved@example.com'});
 vite=spawn(path.join(root,'runtimes/node/bin/node'),['node_modules/vite/bin/vite.js','--config','apps/desktop/vite.config.ts','--port','1448'],{cwd:root,env,stdio:'ignore'});
 for(let i=0;i<80;i++){try{if((await fetch('http://127.0.0.1:1448')).ok)break;}catch{}await new Promise(r=>setTimeout(r,200));}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:940},reducedMotion:'reduce'});page.setDefaultTimeout(15000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:1448');
 async function openSettings(){await page.getByRole('button',{name:'设置',exact:true}).click();await page.locator('.settings-nav').getByRole('button',{name:'PDF 下载',exact:true}).click();}
 await openSettings();
 const zotero=page.locator('.pdf-zotero'),address=page.getByRole('textbox',{name:'Zotero 本地地址',exact:true}),requests=page.locator('.pdf-request-settings');
 const button=(scope,name)=>scope.getByRole('button',{name,exact:true});
 await expect(address).toHaveAttribute('readonly','');await expect(address).toHaveValue('localhost:23120');
 const titles=await page.locator('.pdf-source-card h3,.pdf-mirrors>summary,.pdf-request-settings>summary').evaluateAll(nodes=>nodes.map(n=>{const s=getComputedStyle(n);return [s.fontSize,s.fontWeight,s.fontFamily];}));expect(titles).toHaveLength(4);for(const style of titles)expect(style).toEqual(titles[0]);
 await button(zotero,'编辑').click();await expect(address).toBeEditable();await address.fill('localhost:23121');await button(zotero,'取消').click();await expect(address).toHaveValue('localhost:23120');await expect(address).toHaveAttribute('readonly','');expect(rpc('download.settings').zoteroAddress).toBe('localhost:23120');
 // Saves affect only their section, even when another section has an unsaved draft.
 const email=page.getByRole('textbox',{name:'Unpaywall 联系邮箱',exact:true});await email.fill('draft@example.com');
 await requests.locator('summary').click();for(const input of await requests.locator('input').all())await expect(input).toHaveAttribute('readonly','');
 await button(requests,'编辑').click();const timeout=page.getByRole('spinbutton',{name:'请求超时 · 秒',exact:true});await timeout.fill('35');
 await button(zotero,'编辑').click();await address.fill('localhost:23121');await button(zotero,'保存').click();await expect(address).toHaveAttribute('readonly','');expect(rpc('download.settings').zoteroAddress).toBe('localhost:23121');expect(rpc('download.settings').timeout).toBe(custom.timeout);expect(rpc('download.settings').email).toBe('saved@example.com');await expect(timeout).toHaveValue('35');await expect(email).toHaveValue('draft@example.com');
 await button(requests,'保存').click();await expect(timeout).toHaveAttribute('readonly','');expect(rpc('download.settings').timeout).toBe(35);expect(rpc('download.settings').email).toBe('saved@example.com');await expect(email).toHaveValue('draft@example.com');
 await button(requests,'编辑').click();await timeout.fill('40');await button(requests,'取消').click();await expect(timeout).toHaveValue('35');await expect(timeout).toHaveAttribute('readonly','');expect(rpc('download.settings').timeout).toBe(35);
 await page.getByRole('button',{name:'保存下载设置',exact:true}).click();await expect(page.getByText('下载设置已保存',{exact:true})).toBeVisible();expect(rpc('download.settings').email).toBe('draft@example.com');
 await page.reload();await openSettings();await expect(address).toHaveValue('localhost:23121');await expect(address).toHaveAttribute('readonly','');await requests.locator('summary').click();await expect(timeout).toHaveValue('35');await expect(timeout).toHaveAttribute('readonly','');
 // A failed independent save keeps the draft editable and the saved value intact.
 const rejectSave=async route=>{const body=route.request().postDataJSON();if(body.action==='download.settings.save'&&body.args.zoteroAddress)await route.fulfill({json:{ok:false,error:'fixture save failure'}});else await route.continue();};
 await page.route('**/__research',rejectSave);await button(zotero,'编辑').click();await address.fill('localhost:23122');await button(zotero,'保存').click();await expect(page.getByRole('alert')).toContainText('fixture save failure');await expect(address).toBeEditable();expect(rpc('download.settings').zoteroAddress).toBe('localhost:23121');await page.unroute('**/__research',rejectSave);await button(zotero,'取消').click();
 // Navigation still protects section drafts: cancel one, save the other on leave.
 await button(zotero,'编辑').click();await address.fill('localhost:23122');await page.locator('.settings-nav').getByRole('button',{name:'模型与服务',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Zotero 本地地址');await page.getByRole('button',{name:'不保存并离开',exact:true}).click();await page.locator('.settings-nav').getByRole('button',{name:'PDF 下载',exact:true}).click();await expect(address).toHaveValue('localhost:23121');
 await requests.locator('summary').click();await button(requests,'编辑').click();await timeout.fill('36');await page.locator('.settings-nav').getByRole('button',{name:'模型与服务',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('下载速度与超时');await page.getByRole('button',{name:'保存并离开',exact:true}).click();await page.locator('.settings-nav').getByRole('button',{name:'PDF 下载',exact:true}).click();await requests.locator('summary').click();await expect(timeout).toHaveValue('36');await expect(timeout).toHaveAttribute('readonly','');expect(rpc('download.settings').timeout).toBe(36);
 // Restore uses the backend defaults for all ten settings and persists without a second save.
 await button(zotero,'恢复默认').click();await expect(address).toHaveValue(defaults.zoteroAddress);await expect(address).toHaveAttribute('readonly','');expect(rpc('download.settings').zoteroAddress).toBe(defaults.zoteroAddress);
 await button(requests,'编辑').click();await timeout.fill('41');await button(requests,'恢复默认').click();await expect(timeout).toHaveAttribute('readonly','');const restored=rpc('download.settings');for(const key of requestKeys)expect(restored[key]).toBe(defaults[key]);expect(restored.email).toBe('draft@example.com');
 await mkdir(path.join(root,'docs/screenshots'),{recursive:true});await page.locator('.settings-body').evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(root,'docs/screenshots/download-editors-expanded.png')});
 await requests.locator('summary').click();await page.screenshot({path:path.join(root,'docs/screenshots/download-editors-collapsed.png')});
 await page.setViewportSize({width:900,height:650});await page.getByRole('button',{name:'EN',exact:true}).click();await requests.locator('summary').click();await button(zotero,'Edit').click();await button(requests,'Edit').click();await page.evaluate(()=>document.documentElement.dataset.theme='dark');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);expect(await requests.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(false);
 await page.locator('.settings-body').evaluate(el=>el.scrollTop=0);await page.screenshot({path:path.join(root,'docs/screenshots/download-editors-english-compact.png')});expect(errors).toEqual([]);
 console.log(JSON.stringify({passed:true,checks:['readonly by default','independent save and cancellation','unrelated drafts preserved','reload persistence','save failure preserves edit state','navigation save and discard guards','restore all backend defaults','consistent titles','compact English dark layout'],errors}));
}catch(e){if(browser){const page=browser.contexts()[0]?.pages()[0];await page?.screenshot({path:path.join(root,'tmp/download-editors-failure.png')});}throw e;}
finally{await browser?.close();vite?.kill();await rm(app,{recursive:true,force:true});}
