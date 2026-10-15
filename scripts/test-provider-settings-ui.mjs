// Isolated Vite + real Rust settings RPC. No live model requests or real user data.
import {chromium,expect} from '@playwright/test';
import {mkdir,mkdtemp,cp,symlink,rm,writeFile} from 'node:fs/promises';
import {spawn,execFileSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd(),app=await mkdtemp(path.join(root,'tmp/provider-ui-'));
const env={...process.env,SCHOLARNOTELM_ROOT:app};
function rpc(action,args={}){const r=JSON.parse(execFileSync(path.join(root,'cache/tauri-target/debug/research-cli'),[],{env,input:JSON.stringify({action,args:{project:'provider_ui',...args}}),encoding:'utf8'}));if(!r.ok)throw Error(r.error);return r.data;}
await mkdir(path.join(app,'services'),{recursive:true});await cp(path.join(root,'services/llm_providers'),path.join(app,'services/llm_providers'),{recursive:true});await symlink(path.join(root,'services/downloader'),path.join(app,'services/downloader'));await symlink(path.join(root,'runtimes'),path.join(app,'runtimes'));
await mkdir(path.join(app,'tmp'));await mkdir(path.join(app,'data/reference/jcr'),{recursive:true});await cp(path.join(root,'data/reference/jcr/default-2025.xlsx'),path.join(app,'data/reference/jcr/default-2025.xlsx'));
const project={id:'provider_ui',name:'ProviderUI',description:'Isolated fixture',color:'sage',papers:[],messages:[],sections:[],notes:{},tasks:[]};
rpc('storage.initialize');rpc('storage.register',{folder:'ProviderUI',data:project});rpc('storage.state.write',{state:{version:1,active:project.id,theme:'light',uiLanguage:'zh',projects:[project]}});rpc('mesh.settings',{autoUpdate:false,includeScr:false});
rpc('profile.save',{profile:{id:'ordinary',name:'普通服务',baseUrl:'http://127.0.0.1:9999/v1',model:'ordinary',models:['ordinary'],temperature:null,timeout:120},makeDefault:true});
const vite=spawn(path.join(root,'runtimes/node/bin/node'),['node_modules/vite/bin/vite.js','--config','apps/desktop/vite.config.ts','--port','1447'],{cwd:root,env,stdio:'ignore'});
let browser;
try{
 for(let i=0;i<80;i++){try{if((await fetch('http://127.0.0.1:1447')).ok)break;}catch{}await new Promise(r=>setTimeout(r,200));}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1200,height:850}});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:1447');await page.getByRole('button',{name:'设置',exact:true}).click();
 const group=page.locator('details').filter({has:page.locator('summary strong',{hasText:'opencode_go'})});
 await expect(group).toHaveCount(1);await expect(group).not.toHaveAttribute('open','');await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveValue('普通服务');
 await group.locator('summary').click();await expect(group).toHaveAttribute('open','');await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveValue('opencode_go');
 const base=page.getByRole('textbox',{name:'API 地址',exact:true});await expect(base).toHaveValue('https://opencode.ai/inference/go/v1');await expect(base).toHaveAttribute('readonly','');
 await page.getByRole('textbox',{name:'API Key',exact:true}).fill('fixture-ui-secret');await page.getByRole('button',{name:'手动添加模型',exact:true}).click();await page.getByRole('textbox',{name:'手动模型名称',exact:true}).fill('deepseek-v4.1-flash');await page.getByRole('button',{name:'添加模型',exact:true}).click();
 // Switching providers participates in the existing unsaved-change guard.
 await page.getByRole('button',{name:'配置普通 OpenAI 兼容服务'}).click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'继续编辑',exact:true}).click();
 await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();
 const saved=rpc('profile.list');const go=saved.profiles.find(p=>p.provider==='opencode_go');expect(go.name).toBe('opencode_go');expect(go.hasKey).toBe(true);expect(go.apiKey).toBeUndefined();expect(saved.activeProfile).toBe('ordinary');
 await page.screenshot({path:path.join(app,'provider-open.png'),fullPage:true});
 await page.getByRole('button',{name:'配置普通 OpenAI 兼容服务'}).click();await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveValue('普通服务');await expect(page.getByRole('textbox',{name:'API 地址',exact:true})).not.toHaveAttribute('readonly','');
 await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();await expect(group).not.toHaveAttribute('open','');
 await page.setViewportSize({width:900,height:650});await group.locator('summary').click();expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:path.join(app,'provider-compact.png'),fullPage:true});
 // Remove only the copied plugin: existing Go profiles remain visible as unavailable.
 await rm(path.join(app,'services/llm_providers/opencode_go'),{recursive:true});await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();await group.locator('summary').click();await expect(page.getByText('此供应商已停用；可删除旧配置或选择其他供应商。')).toBeVisible();
 expect(errors).toEqual([]);await mkdir(path.join(root,'docs/screenshots'),{recursive:true});await cp(path.join(app,'provider-open.png'),path.join(root,'docs/screenshots/provider-open.png'));await cp(path.join(app,'provider-compact.png'),path.join(root,'docs/screenshots/provider-compact.png'));
 console.log(JSON.stringify({passed:true,checks:['collapsed provider panel','fixed official URL','real profile persistence and key redaction','normal default unchanged','unsaved-change protection','normal editable connection remains separate','900px no horizontal overflow','removed plugin remains manageable'],errors}));
}catch(e){if(browser){const pages=browser.contexts()[0]?.pages();if(pages?.[0]){console.log((await pages[0].locator('body').innerText()).slice(-6000));await pages[0].screenshot({path:path.join(root,'tmp/provider-ui-failure.png'),fullPage:true});}}throw e;}
finally{await browser?.close();vite.kill();await rm(app,{recursive:true,force:true});}
