import {chromium,expect} from '@playwright/test';
import {mkdtemp,rm,readFile,mkdir} from 'node:fs/promises';
import {spawn,spawnSync} from 'node:child_process';
import {createServer} from 'node:http';
import path from 'node:path';
const root=process.cwd(),fixture=await mkdtemp(path.join(root,'tmp/qa-ui-'));
const modelRequests=[];let protocolMode='normal';
const modelServer=createServer(async(req,res)=>{
 if(req.method==='GET'){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({data:[{id:'flash'},{id:'pro'},{id:'extra-model'}]}));return;}
 let body='';for await(const part of req)body+=part;const request=JSON.parse(body);
 if(request.input){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({data:request.input.map((_,i)=>({index:i,embedding:[1,.2,.3]}))}));return;}
 modelRequests.push(request);const sys=request.messages[0].content,probe=sys==='Reply only: connection OK',outerPayload=probe?{}:JSON.parse(request.messages.at(-1).content),payload=outerPayload.task||outerPayload;let result;
 if(probe)result='connection OK';
 else if(sys.includes('"score"'))result={score:8,relation:'direct',summary:'摘要中的相关发现',context:'摘要材料，需保留适用条件',aspect:'适用范围',quotes:[payload.evidence.text.slice(0,100)]};
 else if(sys.includes('"cards"'))result={cards:payload.evidence.map(r=>({eid:r.eid,relation:'direct',summary:'逐篇阅读发现',context:'摘要',aspect:'适用范围',quotes:[r.text.slice(0,100)]}))};
 else if(sys.includes('"aspects"'))result={aspects:['适用范围'],queries:[{query:'fixture query',purpose:'查找证据'}],tools:['exact'],note:'先确认研究对象与证据类型，再检查适用条件。'};
 else if(sys.includes('"findings"'))result={findings:payload.evidence.map(r=>({eid:r.eid,quote:r.text.slice(0,100),finding:'这些材料属于摘要'}))};
 else if(sys.includes('"coverage"'))result={enough:payload.agentStep>=2,coverage:[{aspect:'适用范围',status:payload.agentStep>=2?'supported':'partial',evidenceIds:['E1'],gap:payload.agentStep>=2?'':'还需核对研究对象'}],queries:[],tools:payload.agentStep>=2?[]:[{tool:'exact',text:'Test source',offset:0}],reason:payload.agentStep>=2?'已找到可用材料':'首轮只找到摘要证据，第二轮精确查找研究对象，核对适用条件'};
 else if(sys.includes('只在存在关键遗漏'))result={enough:true,queries:[],tools:[],reason:'无需补充'};
 else if(sys.includes('核对 draft')){await new Promise(r=>setTimeout(r,2500));result={problems:[{eid:'E1',problem:'draft 中的概括超出该摘要提供的研究条件，请对照原文确认。'}]};}
 else result='这项研究提供了摘要证据，应保留适用条件 [E1]。\n\n| 维度 | 发现 |\n| --- | --- |\n| 材料 | 摘要 [E1] |\n\n现有材料不足以作更广泛的结论。';
 if(protocolMode==='failanswer'&&sys.includes('用中文 Markdown 回答')){res.writeHead(503);res.end();return;}
 if(protocolMode==='failgap'&&sys.includes('"coverage"'))result='{"enough":';
 const text=typeof result==='string'?result:JSON.stringify(result);res.writeHead(200,{'Content-Type':'text/event-stream'});
 for(const part of ['正在核对','研究对象。','随后检查证据范围。']){res.write(`data: ${JSON.stringify({choices:[{delta:{reasoning_content:part}}]})}\n\n`);await new Promise(r=>setTimeout(r,sys.includes('"aspects"')?500:100));}
 for(let i=0;i<text.length;i+=20){res.write(`data: ${JSON.stringify({choices:[{delta:{content:text.slice(i,i+20)}}]})}\n\n`);await new Promise(r=>setTimeout(r,65));}
 res.end('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');
});
await new Promise(r=>modelServer.listen(0,'127.0.0.1',r));const modelPort=modelServer.address().port;
const setup=spawnSync(path.join(root,'runtimes/downloader/bin/python'),['scripts/prepare-workspace-ui.py',fixture],{cwd:root,encoding:'utf8'});if(setup.status!==0)throw Error(setup.stderr);
function rpc(action,args={}){const p=spawnSync(path.join(root,'cache/tauri-target/debug/research-cli'),[],{cwd:root,env:{...process.env,SCHOLARNOTELM_ROOT:fixture},input:JSON.stringify({action,args}),encoding:'utf8'});const result=JSON.parse(p.stdout);if(!result.ok)throw Error(result.error);return result.data;}
rpc('xml.import',{project:'UITest',name:'fixture.xml',xml:await readFile(path.join(fixture,'workspace/UITest/pubmed/current.xml'),'utf8')});
const profile=rpc('profile.save',{profile:{id:'',name:'测试供应商',baseUrl:`http://127.0.0.1:${modelPort}/v1`,model:'pro',models:['pro'],apiKey:'fixture-only',temperature:.3,timeout:10}});
rpc('qa.settings.save',{plannerProfile:profile.id,plannerModel:'pro',answerProfile:profile.id,answerModel:'pro'});
const seeded=spawnSync(path.join(root,'runtimes/downloader/bin/python'),['-c',`import sys,json,struct\nfrom pathlib import Path\nsys.path.insert(0,str(Path.cwd()/'services/downloader'))\nimport engine as e,vector_service as v,vector_chunks as c\ne.ROOT=Path(sys.argv[1]);e.PROJECT='UITest'\nv.rpc(e,'settings.save',{'baseUrl':'http://127.0.0.1:${modelPort}/v1','model':'embed','autoIndex':False})\nc.sync(e)\nwith c.connect(e) as db:\n for d in db.execute('SELECT * FROM current_documents').fetchall():\n  for r in c.records_for(db,d['version'],json.loads(d['meta'])):db.execute('INSERT INTO embeddings VALUES(?,?,?,?)',(v.profile(v.config(e)),c.digest(c.embedding_text(r)),3,struct.pack('<fff',1.,.2,.3)))\nimport retrieval_settings\nretrieval_settings.mark_verified(e,v.config(e),3)`,fixture],{cwd:root,encoding:'utf8'});if(seeded.status!==0)throw Error(seeded.stderr);
// Seed an isolated assistant history so color/layout checks never call a live model.
const chat=rpc('chat.new',{project:'UITest',name:'检索策略与研究对象'});
const chatSeed=spawnSync(path.join(root,'runtimes/downloader/bin/python'),['-c',`import sqlite3,json,sys
from pathlib import Path
base=Path(sys.argv[1])
messages=[{'role':'user','text':'如何设计中性粒细胞参与 HLH 机制的检索策略？','created':1},{'role':'assistant','text':'先以疾病和细胞类型建立基础检索，再补充作用机制。\\n\\n**建议先查看基础检索的覆盖情况。**','reasoning':'需要区分疾病背景与细胞机制，并保留不同研究对象的范围。','created':2,'result':{'queries':[{'id':'fixture-query','name':'疾病与细胞类型','purpose':'定位中性粒细胞与 HLH 的交叉研究。','text':'(hemophagocytic lymphohistiocytosis) AND (neutrophil OR neutrophils)'}],'meshVersion':'fixture','model':'flash'}}]
for db in base.rglob('research.sqlite3'):
 with sqlite3.connect(db) as c:
  try:c.execute('UPDATE chat_threads SET data=? WHERE id=?',(json.dumps(messages,ensure_ascii=False),sys.argv[2]))
  except sqlite3.OperationalError:pass`,fixture,chat.id],{cwd:root,encoding:'utf8'});if(chatSeed.status!==0)throw Error(chatSeed.stderr);
const port=4187,server=spawn(process.execPath,['node_modules/vite/bin/vite.js','preview','--config','apps/desktop/vite.config.ts','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:root,env:{...process.env,SCHOLARNOTELM_ROOT:fixture},stdio:'ignore'});
let browser;
try{
 for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error('Preview failed');try{await fetch(`http://127.0.0.1:${port}`);break;}catch{await new Promise(r=>setTimeout(r,100));}}
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1550,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`http://127.0.0.1:${port}`);
 await page.getByRole('button',{name:'设置',exact:true}).first().click();
 await expect(page.getByLabel('配置名称',{exact:true})).toHaveValue('测试供应商');
 await page.getByRole('button',{name:'获取模型列表',exact:true}).click();
 await expect(page.getByRole('checkbox',{name:'flash',exact:true})).toBeVisible();await page.getByRole('checkbox',{name:'flash',exact:true}).check();
 await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByText('当前配置已保存',{exact:true})).toBeVisible();
 expect(rpc('profile.list').profiles[0].models).toEqual(['pro','flash']);
 await page.getByRole('combobox',{name:'测试模型',exact:true}).click();await page.getByRole('option',{name:'flash',exact:true}).click();
 await page.getByRole('button',{name:'测试模型连接',exact:true}).click();await expect(page.getByText(/流式测试通过 · 直连 API · 测试供应商\/flash/)).toBeVisible({timeout:15000});
 expect(modelRequests.at(-1).model).toBe('flash');expect(rpc('profile.list').profiles[0].model).toBe('pro');
 await expect(page.getByText('灵感在这里，数据也在。',{exact:true})).toHaveCount(0);
 await page.locator('.model-test-panel').scrollIntoViewIfNeeded();await page.screenshot({path:'docs/screenshots/model-test-selection.png'});

 // Settings use isolated real RPC: preserve active embeddings while editing another profile.
 const originalEmbedding=rpc('vector.settings').activeProfile;
 await page.getByRole('button',{name:'PDF 下载',exact:true}).click();await expect(page.locator('.download-route')).toHaveCount(0);
 await expect(page.locator('.settings-advanced')).not.toHaveAttribute('open','');await expect(page.getByText('开启后将延长下载时间',{exact:true})).toBeVisible();
 await expect(page.getByText(/填写个人邮箱即可/)).toBeVisible();await page.locator('.settings-advanced>summary').click();await expect(page.locator('.advanced-settings-grid>details')).toHaveCount(4);await expect(page.locator('.advanced-settings-grid')).toContainText('Sci-Hub 镜像');await expect(page.locator('.advanced-settings-grid')).toContainText('Bloom 索引');await page.screenshot({path:'docs/screenshots/settings-downloads-layered.png'});
 await page.getByRole('button',{name:'Markdown 转换',exact:true}).click();await expect(page.getByLabel('清洗模式')).toHaveValue('保守清洗方案');await expect(page.getByLabel('启用段落清洗')).toBeChecked();await expect(page.getByText('旧 BADR（兼容模式）')).toHaveCount(0);await expect(page.getByText(/额外删除的行/)).toHaveCount(0);
 await page.getByRole('button',{name:'Embedding 模型',exact:true}).click();await page.getByRole('button',{name:'新建配置',exact:true}).click();
 await page.getByLabel('Embedding 配置名称',{exact:true}).fill('备用向量');await page.getByLabel('Embedding API 地址').fill(`http://127.0.0.1:${modelPort}/v1`);await page.getByLabel('Embedding API Key',{exact:true}).fill('fixture-vector-key');
 await page.getByRole('button',{name:'获取模型列表',exact:true}).click();await page.getByRole('combobox',{name:'Embedding 模型列表'}).click();await page.getByRole('option',{name:'flash',exact:true}).click();
 await page.getByRole('button',{name:'验证连接',exact:true}).click();await expect(page.getByText(/备用向量\/flash · 连接成功/)).toBeVisible({timeout:15000});await page.getByRole('button',{name:'保存配置',exact:true}).click();
 await expect(page.getByLabel('Embedding API Key',{exact:true})).toHaveValue('');await expect(page.getByLabel('Embedding API Key',{exact:true})).toHaveAttribute('placeholder','••••••••••••••••');
 await page.getByRole('button',{name:'显示 Embedding 密钥'}).click();await expect(page.getByLabel('Embedding API Key',{exact:true})).toHaveValue('fixture-vector-key');await expect(page.getByLabel('Embedding API Key',{exact:true})).toHaveAttribute('type','text');await page.getByRole('button',{name:'隐藏 Embedding 密钥'}).click();await expect(page.getByLabel('Embedding API Key',{exact:true})).toHaveValue('');
 let embedding=rpc('vector.settings');const extra=embedding.profiles.find(p=>p.name==='备用向量');expect(embedding.activeProfile).toBe(originalEmbedding);expect(JSON.stringify(embedding)).not.toContain('fixture-vector-key');
 await page.screenshot({path:'docs/screenshots/settings-embedding-profiles.png'});
 await page.setViewportSize({width:850,height:650});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.getByLabel('Embedding 配置名称',{exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:'docs/screenshots/settings-embedding-narrow.png'});await page.setViewportSize({width:1550,height:1000});
 await page.getByRole('button',{name:'召回与重排',exact:true}).click();await page.getByRole('combobox',{name:'召回 Embedding 配置'}).click();await page.getByRole('option',{name:'备用向量/flash',exact:true}).click();await page.getByRole('button',{name:'保存检索设置',exact:true}).click();await expect(page.getByText('检索设置已保存',{exact:true})).toBeVisible();expect(rpc('vector.settings').activeProfile).toBe(extra.id);
 await page.screenshot({path:'docs/screenshots/settings-retrieval-profiles.png'});
 await page.getByRole('combobox',{name:'召回 Embedding 配置'}).click();await page.getByRole('option',{name:'默认配置/embed',exact:true}).click();await page.getByRole('button',{name:'保存检索设置',exact:true}).click();await expect.poll(()=>rpc('vector.settings').activeProfile).toBe(originalEmbedding);
 await page.getByRole('button',{name:'文献问答',exact:true}).last().click();
 await expect(page.getByLabel('最多检索轮数')).toHaveValue('3');await expect(page.getByLabel('每个 query 保留块数 b')).toHaveValue('8');
 await expect(page.getByRole('checkbox',{name:'启用 RCS',exact:true})).not.toBeChecked();await page.getByRole('checkbox',{name:'启用 RCS',exact:true}).check();await expect(page.getByLabel('RCS 候选块数 a')).toHaveValue('24');await page.getByLabel('RCS 候选块数 a').fill('16');await expect(page.getByRole('combobox',{name:'证据阅读模型',exact:true})).toBeVisible();await page.screenshot({path:'docs/screenshots/qa-rcs-settings.png'});await page.getByRole('checkbox',{name:'启用 RCS',exact:true}).uncheck();
 await page.getByRole('combobox',{name:'检索规划模型',exact:true}).click();await page.getByRole('option',{name:'测试供应商/flash',exact:true}).click();await page.getByRole('button',{name:'保存问答设置',exact:true}).click();
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'文献问答',exact:true}).click();
 await expect(page.getByRole('complementary',{name:'问答对话管理'})).toBeVisible();await expect(page.getByRole('combobox',{name:'文献问答对话'})).toHaveCount(0);
 await expect(page.getByLabel('文献问答问题')).toBeVisible();await page.locator('.qa-model-picker>summary').click();await expect(page.getByRole('combobox',{name:'检索规划模型',exact:true})).toContainText('flash');
 await expect(page.getByRole('checkbox',{name:/回答后深度核查/})).not.toBeChecked();await page.locator('.qa-model-picker>summary').click();
 await page.getByLabel('文献问答问题').fill('这些研究的证据范围是什么？');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.locator('.qa-event-model.status-running .qa-reasoning-body')).toContainText('正在核对',{timeout:15000});
 await expect(page.locator('.qa-answer')).toHaveCount(0);
 await expect(page.locator('.qa-event-model.status-running .qa-reasoning-body')).toContainText('随后检查证据范围');await page.screenshot({path:'docs/screenshots/qa-reasoning.png'});
 await expect(page.locator('.qa-event-model.status-running .qa-live-output')).toBeVisible({timeout:15000});
 await expect(page.locator('.qa-answer')).toHaveCount(0);
 await mkdir('docs/screenshots',{recursive:true});await page.screenshot({path:'docs/screenshots/qa-streaming.png'});
 await expect(page.locator('.qa-event-tool .qa-query')).toContainText('Test source',{timeout:30000});
 await expect(page.locator('.qa-event-request_validation')).toContainText('exact 仅提供了工具名');await expect(page.locator('.qa-event-request_validation')).toContainText('已跳过');
 await expect(page.locator('.qa-event-round_start').last()).toContainText('首轮只找到摘要证据');
 await expect(page.locator('.qa-answer')).toContainText('摘要证据',{timeout:40000});await expect(page.locator('.qa-answer-head')).toContainText('已完成',{timeout:40000});
 await expect(page.locator('.qa-answer table')).toBeVisible();
 await expect(page.locator('.qa-answer-foot')).toContainText('1 个文本块');
 await expect(page.locator('.qa-trace-toggle')).toHaveAttribute('aria-expanded','false');await page.locator('.qa-trace-toggle').click();
 await expect(page.locator('.qa-trace-toggle')).toContainText('1 项调用已跳过');await page.locator('.qa-event-request_validation details>summary').click();await expect(page.locator('.qa-event-request_validation pre')).toContainText('"exact"');await page.locator('.qa-event-request_validation').scrollIntoViewIfNeeded();await page.screenshot({path:'docs/screenshots/qa-skipped-tool.png'});
 await page.locator('.qa-reasoning>button').first().click();await expect(page.locator('.qa-reasoning-body').first()).toContainText('正在核对研究对象。随后检查证据范围。');await page.locator('.qa-reasoning>button').first().click();
 await page.locator('.qa-event-tool').scrollIntoViewIfNeeded();await page.screenshot({path:'docs/screenshots/qa-tool-details.png'});
 await page.locator('.qa-trace-toggle').click();

 await expect(page.locator('.qa-answer-foot')).toContainText('未启用深度核查');await page.locator('.qa-question').scrollIntoViewIfNeeded();await page.getByLabel('文献问答问题').focus();await expect(page.getByLabel('文献问答问题')).toHaveCSS('outline-style','none');await page.screenshot({path:'docs/screenshots/qa-reading.png'});

 // Branches retain immutable run references; regeneration excludes the old answer.
 await page.context().grantPermissions(['clipboard-read','clipboard-write']);await page.locator('.qa-message-actions').getByRole('button',{name:'复制',exact:true}).click();expect(await page.evaluate(()=>navigator.clipboard.readText())).toContain('摘要证据');
 const originalThread=rpc('qa.list',{project:'UITest'})[0];
 await page.getByRole('button',{name:'重命名问答对话'}).click();await page.getByLabel('新的对话名称').fill('证据范围讨论');await page.getByRole('button',{name:'保存名称',exact:true}).click();await expect(page.locator('.qa-current-thread')).toContainText('证据范围讨论');
 await page.locator('.qa-message-actions').getByRole('button',{name:'从此处分支'}).click();await expect(page.locator('.qa-current-thread')).toContainText('分支');
 let branch=rpc('qa.list',{project:'UITest'})[0];expect(branch.parentId).toBe(originalThread.id);expect(branch.runIds).toEqual(originalThread.runIds);
 await page.locator('.qa-message-actions').getByRole('button',{name:'重新生成'}).click();await expect.poll(()=>rpc('qa.list',{project:'UITest'}).length).toBe(3);await expect(page.locator('.qa-answer-head')).toContainText('进行中',{timeout:15000});await expect(page.locator('.qa-answer-head')).toContainText('已完成',{timeout:40000});
 const regenerated=rpc('qa.list',{project:'UITest'})[0];expect(regenerated.parentId).toBe(branch.id);expect(regenerated.runIds).toHaveLength(1);expect(regenerated.runIds[0]).not.toBe(originalThread.runIds[0]);
 const input=JSON.parse(await readFile(path.join(fixture,'workspace/UITest/qa/runs',regenerated.runIds[0],'input.json'),'utf8'));expect(input.history).toEqual([]);
 await page.getByRole('button',{name:'删除问答对话'}).click();await page.getByRole('dialog').getByRole('button',{name:'删除对话',exact:true}).click();await expect.poll(()=>rpc('qa.list',{project:'UITest'}).length).toBe(2);await expect(page.locator('.qa-answer')).toContainText('摘要证据');
 await page.getByRole('navigation',{name:'文献问答对话'}).getByRole('button',{name:'证据范围讨论',exact:true}).click();await expect(page.locator('.qa-current-thread')).toContainText('证据范围讨论');await expect(page.getByRole('navigation',{name:'文献问答对话'}).getByRole('button',{name:'证据范围讨论',exact:true})).toHaveAttribute('aria-current','page');await page.screenshot({path:'docs/screenshots/qa-conversation-sidebar.png'});
 await page.locator('.qa-citation').first().click();await expect(page.locator('.qa-evidence-detail pre')).toContainText('Test source evidence');
 await mkdir('docs/screenshots',{recursive:true});await page.screenshot({path:'docs/screenshots/qa-desktop.png'});
 await page.getByRole('button',{name:'切换主题',exact:true}).click();await expect(page.locator('.qa-trace-toggle')).toHaveCSS('color','rgb(173, 186, 178)');await page.screenshot({path:'docs/screenshots/qa-dark.png'});await page.getByRole('button',{name:'切换主题',exact:true}).click();
 await page.getByRole('button',{name:'关闭来源面板',exact:true}).click();await expect(page.locator('.qa-evidence')).toBeHidden();
 for(const [width,height] of [[1100,750],[850,600]]){
  await page.setViewportSize({width,height});await expect(page.getByLabel('文献问答问题')).toBeInViewport();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.getByRole('button',{name:'收起对话侧栏'}).click();await expect(page.getByRole('complementary',{name:'问答对话管理'})).toBeHidden();await expect(page.getByLabel('文献问答问题')).toBeInViewport();await page.getByRole('button',{name:'展开对话侧栏'}).click();await expect(page.getByRole('complementary',{name:'问答对话管理'})).toBeVisible();
  await page.locator('.qa-citation').first().click();await expect(page.locator('.qa-evidence-detail')).toBeVisible();await page.getByRole('button',{name:'关闭来源面板',exact:true}).click();
 }
 await page.screenshot({path:'docs/screenshots/qa-narrow.png'});
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出',exact:true}).click();await download;
 await page.reload();await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'文献问答',exact:true}).click();await expect(page.locator('.qa-answer')).toContainText('摘要证据');
 await page.setViewportSize({width:1550,height:1000});
 await page.getByRole('button',{name:'新对话',exact:true}).click();await page.locator('.qa-model-picker>summary').click();await page.getByRole('checkbox',{name:/回答后深度核查/}).check();await expect(page.getByRole('checkbox',{name:/回答后深度核查/})).toBeChecked();await page.locator('.qa-model-picker>summary').click();
 await page.getByLabel('文献问答问题').fill('请核对这份摘要证据的结论。');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.locator('.qa-audit-progress')).toContainText('正文已生成 · 正在深度核查',{timeout:40000});await expect(page.locator('.qa-audit-progress')).toContainText('最多 60 秒');await page.screenshot({path:'docs/screenshots/qa-audit-progress.png'});
 await expect(page.locator('.qa-answer-head')).toContainText('已完成',{timeout:20000});
 await expect(page.locator('.qa-validation>summary')).toContainText('1 处引用表述待确认');await expect(page.locator('.qa-validation-body')).toBeHidden();await page.locator('.qa-validation>summary').click();await expect(page.locator('.qa-validation-body')).toContainText('回答 中的概括');await expect(page.locator('.qa-citation.needs-review').first()).toBeVisible();
 await page.locator('.qa-sources>summary').click();await expect(page.locator('.qa-source-row')).toHaveCount(1);await page.locator('.qa-validation').scrollIntoViewIfNeeded();await page.screenshot({path:'docs/screenshots/qa-review-details.png'});
 protocolMode='failgap';await page.getByRole('button',{name:'新对话',exact:true}).click();await page.locator('.qa-model-picker>summary').click();await page.getByRole('checkbox',{name:/回答后深度核查/}).uncheck();await page.locator('.qa-model-picker>summary').click();
 await page.getByLabel('文献问答问题').fill('格式失败时仍保留原文。');await page.getByRole('button',{name:'发送',exact:true}).click();
 await expect(page.locator('.qa-event-protocol.status-running')).toContainText('正在修复一次',{timeout:40000});
 await expect(page.locator('.qa-answer-head')).toContainText('已完成',{timeout:40000});await expect(page.locator('.qa-answer')).toContainText('摘要证据');await expect(page.locator('.qa-recovery-notice>summary')).toContainText('部分步骤未完成');
 await expect(page.locator('.qa-page .wb-alert')).toHaveCount(0);await page.locator('.qa-recovery-notice>summary').click();await expect(page.locator('.qa-recovery-notice')).toContainText('基于已获得原文作有限回答');await page.screenshot({path:'docs/screenshots/qa-protocol-recovery.png'});
 await page.locator('.qa-trace-toggle').click();await expect(page.locator('.qa-event-protocol.status-warning')).toHaveCount(2);await page.locator('.qa-event-protocol.status-warning').last().scrollIntoViewIfNeeded();await page.screenshot({path:'docs/screenshots/qa-protocol-details.png'});protocolMode='normal';
 // Exercise new agent controls through the real settings, worker, and evidence UI.
 await page.getByRole('button',{name:'新对话',exact:true}).click();await page.locator('.qa-model-picker>summary').click();await page.getByRole('checkbox',{name:'本轮启用 RCS'}).check();await expect.poll(()=>rpc('qa.settings').rcsEnabled).toBe(true);await page.locator('.qa-model-picker>summary').click();
 await page.getByLabel('文献问答问题').fill('启用 RCS 整理相关证据。');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.qa-answer-head')).toContainText('已完成',{timeout:40000});await expect(page.locator('.qa-reading-progress')).toContainText('RCS 已评估 1 块');
 await page.locator('.qa-citation').first().click();await expect(page.locator('.qa-card-detail')).toContainText('相关性 8/10');await expect(page.locator('.qa-card-detail blockquote')).toContainText('Test source');await page.screenshot({path:'docs/screenshots/qa-rcs-card.png'});await page.getByRole('button',{name:'关闭来源面板'}).click();
 await page.getByRole('button',{name:'新对话',exact:true}).click();await page.locator('.qa-model-picker>summary').click();await page.getByRole('checkbox',{name:'本轮启用 RCS'}).uncheck();await expect.poll(()=>rpc('qa.settings').rcsEnabled).toBe(false);await page.locator('.qa-model-picker>summary').click();
 await page.getByRole('combobox',{name:'文献阅读模式'}).click();await page.getByRole('option',{name:'项目概览 · 逐篇阅读',exact:true}).click();await page.getByLabel('文献问答问题').fill('逐篇比较这些论文。');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.qa-answer-head')).toContainText('已完成',{timeout:40000});await page.locator('.qa-reading-progress>summary').click();await expect(page.locator('.qa-reading-progress')).toContainText('材料未准备');await expect(page.locator('.qa-reading-progress')).toContainText('仅摘要');await page.screenshot({path:'docs/screenshots/qa-project-reading.png'});
 await page.getByRole('button',{name:'新对话',exact:true}).click();await page.getByRole('combobox',{name:'文献阅读模式'}).click();await page.getByRole('option',{name:'单篇精读',exact:true}).click();await page.getByLabel('文献问答问题').fill('精读这篇论文。');await expect(page.getByRole('button',{name:'发送',exact:true})).toBeDisabled();await page.locator('.qa-paper').filter({hasText:'Abstract paper'}).getByRole('checkbox').check();await page.getByRole('button',{name:'关闭来源面板'}).click();await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.locator('.qa-answer-head')).toContainText('已完成',{timeout:40000});await expect(page.locator('.qa-reading-progress')).toContainText('已读材料涉及 1 / 1 篇');
 protocolMode='failanswer';await page.getByRole('button',{name:'新对话',exact:true}).click();await page.getByLabel('文献问答问题').fill('检验中断后继续。');await page.getByRole('button',{name:'发送',exact:true}).click();await expect(page.getByRole('button',{name:'继续未完成步骤'})).toBeVisible({timeout:40000});const beforeResume=modelRequests.length;protocolMode='normal';await page.getByRole('button',{name:'继续未完成步骤'}).click();await expect(page.locator('.qa-answer-head').last()).toContainText('已完成',{timeout:40000});expect(modelRequests.length-beforeResume).toBe(1);await page.screenshot({path:'docs/screenshots/qa-resume.png'});
 for(const name of ['第一条','第二条','已禁用','已归档'])rpc('query.save',{project:'UITest',name,text:`fixture ${name}`});
 let workspace=rpc('workspace',{project:'UITest'});rpc('query.toggle',{project:'UITest',id:workspace.queries.find(q=>q.name==='已禁用').id,value:false});rpc('query.archive',{project:'UITest',id:workspace.queries.find(q=>q.name==='已归档').id,value:true});workspace=rpc('workspace',{project:'UITest'});
 const expectedQueries=workspace.queries.filter(q=>q.enabled&&!q.archived&&q.source!=='import'&&q.text.trim()).map(q=>q.id),runs=[];let concurrent=0,maxConcurrent=0;
 const intercept=async route=>{const request=route.request().postDataJSON();if(request.action!=='query.run')return route.continue();const run={id:request.args.id,start:Date.now(),end:0};runs.push(run);concurrent++;maxConcurrent=Math.max(concurrent,maxConcurrent);await new Promise(r=>setTimeout(r,150));concurrent--;run.end=Date.now();await route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,data:workspace})});};
 await page.route('**/__research',intercept);
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'检索工作台',exact:true}).click();
 await page.getByRole('button',{name:'执行全部',exact:true}).click();await expect(page.locator('.wb-working')).toContainText('等待 2 秒');
 await page.screenshot({path:'docs/screenshots/search-batch.png'});await expect(page.locator('.wb-working')).toBeHidden({timeout:10000});
 expect(runs.map(r=>r.id)).toEqual(expectedQueries);expect(maxConcurrent).toBe(1);for(let i=1;i<runs.length;i++)expect(runs[i].start-runs[i-1].end).toBeGreaterThanOrEqual(1950);
 const completed=runs.length;await page.getByRole('button',{name:'执行全部',exact:true}).click();await expect(page.locator('.wb-working')).toContainText('等待 2 秒');
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'文献问答',exact:true}).click();await page.waitForTimeout(2300);expect(runs.length).toBe(completed+1);await page.unroute('**/__research',intercept);
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'检索工作台',exact:true}).click();
 await page.getByRole('tab',{name:'检索助手',exact:true}).click();

 await page.getByRole('button',{name:'重命名对话',exact:true}).click();await page.getByLabel('对话名称',{exact:true}).fill('检索计划');await page.getByRole('button',{name:'保存名称',exact:true}).click();await expect(page.locator('.chat-current-title h3')).toHaveText('检索计划');
 await page.getByRole('button',{name:'从此处分支',exact:true}).last().click();await expect(page.locator('.chat-current-title h3')).toContainText('分支');
 const searchBranch=rpc('chat.list',{project:'UITest'}).find(t=>t.parentId);await page.locator('.chat-thread-list').getByRole('button',{name:'检索计划',exact:true}).click();
 await page.getByRole('button',{name:'删除检索对话'}).click();await page.getByRole('dialog').getByRole('button',{name:'删除对话',exact:true}).click();await expect.poll(()=>rpc('chat.list',{project:'UITest'}).length).toBe(1);await expect(page.locator('.chat-current-title h3')).toContainText('分支');
 await page.getByRole('button',{name:'新建对话',exact:true}).click();await expect(page.locator('.wb-chat-intro')).toBeVisible();await page.locator('.chat-thread-list').getByRole('button',{name:searchBranch.name,exact:true}).click();
 await expect(page.locator('.chat-proposal-action')).toBeVisible();await page.screenshot({path:'docs/screenshots/search-chat-colors.png'});
 await page.getByRole('button',{name:'切换主题',exact:true}).click();await expect(page.locator('.chat-foldout-toggle').first()).toHaveCSS('color','rgb(172, 203, 199)');await page.screenshot({path:'docs/screenshots/search-chat-dark.png'});
 await page.setViewportSize({width:850,height:600});await expect(page.getByLabel('研究需求')).toBeInViewport();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);

 await page.setViewportSize({width:1550,height:1000});await page.getByRole('button',{name:'切换主题',exact:true}).click();
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'综述工作台',exact:true}).click();await page.getByRole('tab',{name:'综述撰写',exact:true}).click();await expect(page.getByLabel('撰写并发数')).toHaveValue('3');
 await page.getByLabel('撰写并发数').fill('');await expect(page.getByLabel('撰写并发数')).toHaveValue('');await page.getByLabel('撰写并发数').fill('7');await page.getByLabel('每节文本块数量').fill('');await expect(page.getByLabel('每节文本块数量')).toHaveValue('');await page.getByLabel('每节文本块数量').fill('9');await page.getByRole('button',{name:'保存参数',exact:true}).click();await expect(page.getByText('撰写参数已保存',{exact:true})).toBeVisible();
 expect(rpc('review.writing.status',{project:'UITest',name:'Existing'}).config.concurrency).toBe(7);await expect(page.locator('.writing-model')).toContainText('测试供应商/pro');await page.screenshot({path:'docs/screenshots/review-writing-layered.png'});
 await page.keyboard.press('Meta+,');await expect(page.locator('.research-settings')).toBeVisible();
 expect(errors).toEqual([]);console.log(JSON.stringify({success:true,checks:['RCS settings a/b and toggle, scored source card and quotes, exhaustive project coverage, single-paper scope, resume only failed model call','QA sidebar new, select, rename, delete and collapse across desktop/narrow layouts','bounded format repair streams and falls back to sourced answer with explicit limits','QA rename, copy, branch, regenerate and delete preserve original runs','search conversation rename, branch, delete and new conversation','Embedding multiple profiles, model list, test, masked key and explicit reveal','recall selects verified saved Embedding profile without erasing cached vectors','PDF advanced groups collapsed by default and concise descriptions','conservative Markdown cleaning is the only UI mode','numeric fields stay empty while editing and save valid replacements','configuration/model display names','Meta+Comma opens settings','layered settings, chat, review and narrow layouts','incomplete tool call is visible and skipped without aborting answer','explicit connection-test model without changing default','provider reasoning streams before content and persists','sidebar promotional card removed','sequential XML retrieval with at least 2s pause','leaving page prevents subsequent retrieval','muted dark accents in light mode','provider multi-select persists','shared advanced settings','QA settings','default no post-answer verification','optional audit progress and elapsed time','collapsed review issues and marked citations','grouped sources','single composer focus ring','different model roles','real RPC and worker','partial tool output before answer','second-round reason and exact tool parameters','completed evidence counts','light and dark contrast','search assistant layout','answer and GFM table','click citation reads actual snapshot','desktop and narrow layout','composer stays visible','export and reload history','no React errors']}));
}finally{if(browser)await browser.close();server.kill();await new Promise(r=>server.once('exit',r));await new Promise(r=>modelServer.close(r));await rm(fixture,{recursive:true,force:true,maxRetries:10,retryDelay:200});}
