// Isolated Vite + real Rust settings RPC. No live model requests or real user data.
import {chromium,expect} from '@playwright/test';
import {mkdir,mkdtemp,cp,symlink,rm,writeFile,readFile} from 'node:fs/promises';
import {spawn,execFileSync} from 'node:child_process';
import path from 'node:path';
import {createServer} from 'node:http';
const root=process.cwd(),app=await mkdtemp(path.join(root,'tmp/provider-ui-'));
const env={...process.env,SCHOLARNOTELM_ROOT:app};
function rpc(action,args={}){const r=JSON.parse(execFileSync(path.join(root,'cache/tauri-target/debug/research-cli'),[],{env,input:JSON.stringify({action,args:{project:'provider_ui',...args}}),encoding:'utf8'}));if(!r.ok)throw Error(r.error);return r.data;}
await mkdir(path.join(app,'services'),{recursive:true});await cp(path.join(root,'services/llm_providers'),path.join(app,'services/llm_providers'),{recursive:true});await symlink(path.join(root,'services/downloader'),path.join(app,'services/downloader'));await symlink(path.join(root,'runtimes'),path.join(app,'runtimes'));
await mkdir(path.join(app,'tmp'));await mkdir(path.join(app,'data/reference/jcr'),{recursive:true});await cp(path.join(root,'services/reference/jcr/default-2025.xlsx'),path.join(app,'data/reference/jcr/default-2025.xlsx'));
const project={id:'provider_ui',name:'ProviderUI',description:'Isolated fixture',color:'sage',papers:[{id:'fixture-paper',title:'Layout fixture paper',author:'Fixture',year:2026,status:'pdf',starred:false}],messages:[],sections:[],notes:{},tasks:[]};
rpc('storage.initialize');rpc('storage.register',{folder:'ProviderUI',data:project});rpc('storage.state.write',{state:{version:1,active:project.id,theme:'light',uiLanguage:'zh',projects:[project]}});rpc('mesh.settings',{autoUpdate:false,includeScr:false});
rpc('query.create');
rpc('profile.save',{profile:{id:'ordinary',name:'opencode_go',baseUrl:'http://127.0.0.1:9999/v1',model:'ordinary',models:['ordinary'],temperature:null,timeout:120},makeDefault:true});
const vite=spawn(path.join(root,'runtimes/node/bin/node'),['node_modules/vite/bin/vite.js','--config','apps/desktop/vite.config.ts','--port','1447'],{cwd:root,env,stdio:'ignore'});
let browser;
let embeddingRequests=0;
const embeddingServer=createServer((req,res)=>{let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{const input=JSON.parse(body).input;embeddingRequests++;res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({data:input.map((_,index)=>({index,embedding:[1,2,3]}))}));});});
await new Promise(resolve=>embeddingServer.listen(0,'127.0.0.1',resolve));
try{
 for(let i=0;i<80;i++){try{if((await fetch('http://127.0.0.1:1447')).ok)break;}catch{}await new Promise(r=>setTimeout(r,200));}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1200,height:850},reducedMotion:'reduce'});page.setDefaultTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:1447');await page.getByRole('button',{name:'设置',exact:true}).click();
 const group=page.getByRole('navigation',{name:'模型供应商',exact:true});
 const goButton=group.getByRole('button',{name:/^opencode_go (内置供应商|已停用)/});
 const ordinaryButton=group.getByRole('button',{name:/^opencode_go OpenAI/});
 await expect(goButton).toHaveCount(1);await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveValue('opencode_go');
 await goButton.click();await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveAttribute('readonly','');
 await expect(page.getByRole('combobox',{name:'已保存的配置',exact:true})).toHaveCount(0);
 const base=page.getByRole('textbox',{name:'API 地址',exact:true});await expect(base).toHaveValue('https://opencode.ai/inference/go/v1');await expect(base).toHaveAttribute('readonly','');
 await page.getByRole('textbox',{name:'API Key',exact:true}).fill('fixture-ui-secret');await page.getByRole('button',{name:'手动添加模型',exact:true}).click();await page.getByRole('textbox',{name:'手动模型名称',exact:true}).fill('deepseek-v4.1-flash');await page.getByRole('button',{name:'添加模型',exact:true}).click();
 for(const model of ['gemini-4-argon-contributor','deepseek-v4-pro','minimax-m2.7','qwen3.8-max']){await page.getByRole('textbox',{name:'手动模型名称',exact:true}).fill(model);await page.getByRole('button',{name:'添加模型',exact:true}).click();}
 await page.getByRole('checkbox',{name:'gemini-4-argon-contributor 支持图片输入',exact:true}).check();
 async function effort(model,options,selection){const control=page.getByRole('combobox',{name:model+' 思考强度',exact:true});await control.click();await expect(page.getByRole('listbox').getByRole('option')).toHaveText(['服务端默认',...options]);await page.getByRole('option',{name:selection,exact:true}).click();}
 await effort('deepseek-v4.1-flash',['low','high','max'],'max');await effort('gemini-4-argon-contributor',['low','medium','high'],'medium');await effort('deepseek-v4-pro',['high','max'],'high');
 await expect(page.getByRole('combobox',{name:'minimax-m2.7 思考强度',exact:true})).toBeDisabled();
 await effort('qwen3.8-max',['low','medium','xhigh','enabled','disabled','budget'],'budget');
 await page.getByRole('spinbutton',{name:'qwen3.8-max 思考 token 预算',exact:true}).fill('262144');
 // Switching providers participates in the existing unsaved-change guard.
 await ordinaryButton.click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'继续编辑',exact:true}).click();
 await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();
 const saved=rpc('profile.list');const go=saved.profiles.find(p=>p.provider==='opencode_go');expect(go.name).toBe('opencode_go');expect(go.hasKey).toBe(true);expect(go.apiKey).toBeUndefined();expect(saved.activeProfile).toBe('ordinary');expect(saved.profiles.filter(p=>p.provider==='opencode_go')).toHaveLength(1);expect(go.reasoningByModel).toEqual({'deepseek-v4.1-flash':'max','gemini-4-argon-contributor':'medium','deepseek-v4-pro':'high','qwen3.8-max':'budget'});expect(go.reasoningBudgetByModel).toEqual({'qwen3.8-max':262144});

 const keyInput=page.getByRole('textbox',{name:'API Key',exact:true});
 for(let i=0;i<2;i++){
  await page.getByRole('button',{name:'显示 API 密钥',exact:true}).click();await expect(keyInput).toHaveAttribute('type','text');await expect(keyInput).toHaveValue('fixture-ui-secret');
  const eye=page.getByRole('button',{name:'隐藏 API 密钥',exact:true});const inputBox=await keyInput.boundingBox(),eyeBox=await eye.boundingBox();expect(eyeBox.y).toBeGreaterThanOrEqual(inputBox.y);expect(eyeBox.y+eyeBox.height).toBeLessThanOrEqual(inputBox.y+inputBox.height+1);
  await eye.click();await expect(keyInput).toHaveAttribute('type','password');await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();
 }
 await page.route('**/__research',async route=>{const body=route.request().postDataJSON();if(body.action==='llm.test'){await new Promise(r=>setTimeout(r,700));await route.fulfill({json:{ok:true,data:{seconds:0.7,reply:'fixture'}}});}else await route.continue();});
 await page.locator('.model-unified-row').first().scrollIntoViewIfNeeded();
 const row=page.locator('.model-unified-row').nth(1);const rowPosition=()=>row.evaluate(el=>el.getBoundingClientRect().y+document.querySelector('.settings-body').scrollTop);const before=await rowPosition();await page.getByRole('button',{name:'测试连接',exact:true}).first().click();await expect(page.getByText('正在测试…',{exact:true})).toBeVisible();expect(Math.abs((await rowPosition())-before)).toBeLessThan(1);await expect(page.getByText('连接通过 · 0.7 秒',{exact:true})).toBeVisible();expect(Math.abs((await rowPosition())-before)).toBeLessThan(1);
 const nav=page.locator('.settings-nav');const navBefore=await nav.boundingBox();await page.locator('.settings-body').evaluate(el=>el.scrollTop=el.scrollHeight);expect(Math.abs((await nav.boundingBox()).y-navBefore.y)).toBeLessThan(1);expect(await page.locator('.main-content').evaluate(el=>el.scrollTop)).toBe(0);
 await page.locator('.model-choice-box').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(app,'provider-open.png'),fullPage:true});
 await ordinaryButton.click();await expect(page.getByRole('textbox',{name:'配置名称',exact:true})).toHaveValue('opencode_go');await expect(page.getByRole('textbox',{name:'API 地址',exact:true})).not.toHaveAttribute('readonly','');await expect(page.getByRole('button',{name:'新建供应商',exact:true})).toBeVisible();await expect(page.getByRole('combobox',{name:/思考强度/})).toHaveCount(0);

 const presetControl=page.getByRole('combobox',{name:'ordinary 思考预设',exact:true});
 await presetControl.click();await expect(page.getByRole('listbox').getByRole('option')).toHaveText(['服务端默认',...JSON.parse(await readFile(path.join(root,'services/downloader/thinking_presets.json'),'utf8')).map(p=>p.name)]);
 await page.getByRole('option',{name:'Generic · Reasoning Effort',exact:true}).click();
 await expect(page.getByRole('combobox',{name:'ordinary 思考强度',exact:true})).toContainText('default');
 await page.setViewportSize({width:900,height:650});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await presetControl.click();await page.getByRole('option',{name:'Gemini 4 · Native',exact:true}).click();
 const ordinaryEffort=page.getByRole('combobox',{name:'ordinary 思考强度',exact:true});
 await expect(ordinaryEffort).toContainText('medium');await ordinaryEffort.click();await page.getByRole('option',{name:'high',exact:true}).click();
 await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();
 expect(rpc('profile.list').profiles.find(p=>p.id==='ordinary').thinkingByModel).toEqual({ordinary:{preset:'gemini4_native',level:'high'}});
 await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();await expect(presetControl).toContainText('Gemini 4 · Native');await expect(ordinaryEffort).toContainText('high');
 await page.setViewportSize({width:900,height:650});await page.locator('.model-choice-box').scrollIntoViewIfNeeded();expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:path.join(app,'thinking-native-compact.png'),fullPage:true});
 await presetControl.click();await page.getByRole('option',{name:'DeepSeek · OpenAI Compatible',exact:true}).click();await ordinaryEffort.click();await expect(page.getByRole('listbox').getByRole('option')).toHaveText(['low','high','max']);await page.getByRole('option',{name:'max',exact:true}).click();
 await presetControl.click();await page.getByRole('option',{name:'服务端默认',exact:true}).click();await expect(ordinaryEffort).toHaveCount(0);await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();
 expect(rpc('profile.list').profiles.find(p=>p.id==='ordinary').thinkingByModel).toEqual({});
 await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();await expect(ordinaryButton).toHaveAttribute('aria-pressed','true');
 await page.setViewportSize({width:900,height:650});await goButton.click();expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await expect(page.getByRole('combobox',{name:'deepseek-v4.1-flash 思考强度',exact:true})).toContainText('max');await expect(page.getByRole('combobox',{name:'gemini-4-argon-contributor 思考强度',exact:true})).toContainText('medium');
 await effort('deepseek-v4.1-flash',['low','high','max'],'服务端默认');await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();expect(rpc('profile.list').profiles.find(p=>p.provider==='opencode_go').reasoningByModel).toEqual({'gemini-4-argon-contributor':'medium','deepseek-v4-pro':'high','qwen3.8-max':'budget'});expect(go.reasoningBudgetByModel).toEqual({'qwen3.8-max':262144});
 await page.screenshot({path:path.join(app,'provider-compact.png'),fullPage:true});
 await mkdir(path.join(root,'docs/screenshots'),{recursive:true});await page.evaluate(()=>document.documentElement.dataset.theme='dark');await page.screenshot({path:path.join(root,'docs/screenshots/provider-dark.png'),fullPage:true});await page.evaluate(()=>delete document.documentElement.dataset.theme);

 await page.setViewportSize({width:1440,height:940});
 await group.getByRole('button',{name:/^DeepSeek 内置供应商/}).click();
 await expect(page.getByRole('textbox',{name:'API 地址',exact:true})).toHaveValue('https://api.deepseek.com/v1');
 await page.getByRole('button',{name:'手动添加模型',exact:true}).click();
 await page.getByRole('textbox',{name:'手动模型名称',exact:true}).fill('deepseek-flash');await page.getByRole('button',{name:'添加模型',exact:true}).click();
 await effort('deepseek-flash',['low','high','max'],'high');await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();
 expect(rpc('profile.list').profiles.find(p=>p.provider==='deepseek').reasoningByModel).toEqual({'deepseek-flash':'high'});
 await page.screenshot({path:path.join(root,'docs/screenshots/provider-deepseek.png'),fullPage:true});

 // Built-in embedding entries persist alongside user configurations, without network calls.
 await page.getByRole('button',{name:'文献检索模型',exact:true}).click();
 const embeddingSelect=page.getByRole('combobox',{name:'检索模型配置',exact:true});
 await embeddingSelect.click();await expect(page.getByRole('listbox').getByRole('option')).toHaveText(['新建配置','siliconflow · 内置预设','jina · 内置预设']);
 await page.getByRole('option',{name:'jina · 内置预设',exact:true}).click();
 await expect(page.getByRole('button',{name:'删除此配置',exact:true})).toBeDisabled();
 await expect(page.getByRole('combobox',{name:'服务商预设',exact:true})).toHaveCount(0);
 const description=page.getByText('用于查找相关原文。请选择服务商提供的 Embedding 模型。',{exact:true});
 const desc=await description.boundingBox(),selector=await embeddingSelect.boundingBox();expect(selector.y-(desc.y+desc.height)).toBeLessThan(65);
 await page.getByRole('textbox',{name:'Embedding API Key',exact:true}).fill('embedding-fixture');
 await page.getByRole('button',{name:'仅保存配置',exact:true}).click();
 await expect(page.getByRole('textbox',{name:'Embedding API Key',exact:true})).toHaveValue('');
 expect(rpc('vector.settings').profiles.find(p=>p.id==='builtin_jina').hasKey).toBe(true);
 // Binding requires verified connectivity. Failure must truthfully report that saving succeeded.
 await page.getByRole('button',{name:'保存并用于当前项目',exact:true}).click();
 await expect(page.getByRole('alert').filter({hasText:'配置已保存，但未用于当前项目'})).toBeVisible();
 await page.getByRole('textbox',{name:'Embedding API 地址',exact:true}).fill(`http://127.0.0.1:${embeddingServer.address().port}/v1`);
 await page.getByRole('button',{name:'验证连接',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'连接成功'})).toBeVisible();
 await page.getByRole('button',{name:'保存并用于当前项目',exact:true}).click();await expect(page.getByText('配置已保存并用于当前项目',{exact:true})).toBeVisible();
 expect(rpc('vector.settings').projectModel.id).toBe('builtin_jina');expect(embeddingRequests).toBe(1);
 await page.getByRole('button',{name:'新建配置',exact:true}).click();
 await page.getByRole('textbox',{name:'检索模型配置名称',exact:true}).fill('Alternate');
 await page.getByRole('textbox',{name:'Embedding API 地址',exact:true}).fill('https://fixture.invalid/v1');
 await page.getByRole('textbox',{name:'检索模型名称',exact:true}).fill('other-model');await page.getByRole('button',{name:'仅保存配置',exact:true}).click();
 await expect(page.getByRole('textbox',{name:'检索模型配置名称',exact:true})).toHaveValue('Alternate');
 await expect(embeddingSelect).toContainText('Alternate');expect(rpc('vector.settings').projectModel.id).toBe('builtin_jina');
 await embeddingSelect.click();await page.getByRole('option',{name:/^jina · 内置预设/}).click();
 await page.screenshot({path:path.join(root,'docs/screenshots/embedding-settings.png'),fullPage:true});
 await page.getByRole('button',{name:'模型与服务',exact:true}).click();
 // Selection and source mutation are real local UI operations against this isolated project.
 await page.getByRole('button',{name:'文献库',exact:true}).click();await expect(page.locator('.paper-row')).toHaveCount(1);
 const paper=page.locator('.paper-row'),paperPosition=()=>paper.evaluate(el=>el.getBoundingClientRect().y+document.querySelector('.main-content').scrollTop),paperY=await paperPosition();await page.getByRole('checkbox',{name:'选择 fixture-paper',exact:true}).check();expect(Math.abs((await paperPosition())-paperY)).toBeLessThan(1);await page.getByRole('button',{name:'取消选择',exact:true}).click();expect(Math.abs((await paperPosition())-paperY)).toBeLessThan(1);
 await page.getByRole('button',{name:'检索工作台',exact:true}).click();await expect(page.locator('.query-table tbody tr')).toHaveCount(1);
 await page.route('**/__research',async route=>{if(route.request().postDataJSON().action==='query.toggle')await new Promise(r=>setTimeout(r,700));await route.fallback();});
 const query=page.locator('.query-table tbody tr'),queryPosition=()=>query.evaluate(el=>el.getBoundingClientRect().y+document.querySelector('.main-content').scrollTop),queryY=await queryPosition();await query.getByRole('checkbox').click();await expect(page.locator('.query-feedback')).toContainText('正在处理');expect(Math.abs((await queryPosition())-queryY)).toBeLessThan(1);await expect(query.getByRole('checkbox')).toBeEnabled();expect(Math.abs((await queryPosition())-queryY)).toBeLessThan(1);
 await page.getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('button',{name:'EN',exact:true}).click();
 await page.setViewportSize({width:900,height:650});
 await expect(page.getByRole('navigation',{name:'Model providers',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:path.join(root,'docs/screenshots/provider-english.png'),fullPage:true});
 await page.getByRole('button',{name:'中文',exact:true}).click();
 await page.getByRole('button',{name:'使用帮助',exact:true}).click();
 await expect(page.getByRole('link',{name:'alanlemonade@gmail.com',exact:true})).toHaveAttribute('href','mailto:alanlemonade@gmail.com');
 await expect(page.getByRole('link',{name:'github.com/XinYu-pumch/ScholarNoteLM',exact:true})).toHaveAttribute('href','https://github.com/XinYu-pumch/ScholarNoteLM');
 await expect(page.getByText('研究工作台 · v0.6.5',{exact:true})).toBeVisible();await page.getByRole('button',{name:'开始探索',exact:true}).click();
 // Remove only the copied plugin: existing Go profiles remain visible as unavailable.
 await rm(path.join(app,'services/llm_providers/opencode_go'),{recursive:true});await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();await goButton.click();await expect(page.getByText('此供应商已停用；可删除旧配置或选择其他供应商。')).toBeVisible();
 expect(errors).toEqual([]);await mkdir(path.join(root,'docs/screenshots'),{recursive:true});await cp(path.join(app,'thinking-native-compact.png'),path.join(root,'docs/screenshots/thinking-native-compact.png'));await cp(path.join(app,'provider-open.png'),path.join(root,'docs/screenshots/provider-open.png'));await cp(path.join(app,'provider-compact.png'),path.join(root,'docs/screenshots/provider-compact.png'));
 console.log(JSON.stringify({passed:true,checks:['ordinary per-model preset selection, reload, levels and removal','key toggles twice without dirtying or leaving input','model testing preserves row positions','settings nav stays fixed while content scrolls','library selection preserves paper position','query toggle preserves source position','singleton provider with fixed name','per-model effort options and persistence','default omits effort','provider sidebar and separate detail editor','fixed official URL','real profile persistence and key redaction','normal default unchanged','unsaved-change protection','normal editable connection remains separate','900px no horizontal overflow','removed plugin remains manageable'],errors}));
}catch(e){if(browser){const pages=browser.contexts()[0]?.pages();if(pages?.[0]){console.log((await pages[0].locator('body').innerText()).slice(-6000));await pages[0].screenshot({path:path.join(root,'tmp/provider-ui-failure.png'),fullPage:true});}}throw e;}
finally{await browser?.close();embeddingServer.close();vite.kill();await rm(app,{recursive:true,force:true});}
