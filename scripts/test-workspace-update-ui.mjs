import {chromium,expect} from '@playwright/test';
import {mkdir,mkdtemp,rm} from 'node:fs/promises';
import {spawn,spawnSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd();const fixture=await mkdtemp(path.join(root,'tmp/workspace-ui-'));
const setup=spawnSync(path.join(root,'runtimes/downloader/bin/python'),['scripts/prepare-workspace-ui.py',fixture],{cwd:root,encoding:'utf8'});if(setup.status!==0)throw Error(setup.stderr);
const port=Number(process.env.UI_TEST_PORT||4174);
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','preview','--config','apps/desktop/vite.config.ts','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:root,env:{...process.env,SCHOLARNOTELM_ROOT:fixture},stdio:'ignore'});
let ready=false;for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error('Preview server failed to start');try{await fetch(`http://127.0.0.1:${port}`);ready=true;break;}catch{await new Promise(r=>setTimeout(r,100));}}if(!ready){server.kill();throw Error('Preview timeout');}
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1050}});const errors=[];const mutations=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/__research',async route=>{
 const req=route.request().postDataJSON();
 if(req.action==='workspace')return route.fulfill({json:{ok:true,data:{queries:[],chats:[],corpus:{snapshot:'test',papers:[1,2].map(i=>({id:'PMID-'+i,pmid:String(i),title:i===1?'Long complete title':'Abstract paper',author:'Test Author',journal:'Full Journal',year:2026,abstract:'Source evidence. '.repeat(20),included:true,reason:'',sources:[],jcr:{},doi:'',pmcid:'',status:'abstract'})),included:2,excluded:0,path:''},conversation:[]}}});
 if(['library.start','download.start','markdown.start','vector.start','library.clear'].includes(req.action)){mutations.push(req);return route.fulfill({json:{ok:true,data:{id:'simulated-job'}}});}
 if(req.action==='vector.status'){
  const response=await route.fetch();const data=await response.json();data.data.configured=true;return route.fulfill({json:data});
 }
 await route.continue();
});
const nav=()=>page.getByRole('navigation',{name:'主导航'});
try{
 await page.goto(`http://127.0.0.1:${port}`);
 await expect(nav().getByRole('button')).toHaveText(['项目概览','检索工作台','文献库2','综述工作台','文献问答','阅读与笔记']);
 await expect(page.getByRole('heading',{name:'界面验证项目',exact:true}).first()).toBeVisible();await expect(page.getByText('我的研究项目')).toHaveCount(0);await expect(page.getByText('已索引示例')).toHaveCount(0);
 await nav().getByRole('button',{name:'综述工作台',exact:true}).click();
 const title=page.getByRole('textbox',{name:'标题 1',exact:true});await expect(title).toHaveAttribute('readonly','');await expect(page.getByRole('button',{name:'CSV 编辑',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'编辑',exact:true}).click();await title.fill('准备取消的修改');await page.getByRole('button',{name:'取消编辑',exact:true}).click();await expect(title).toHaveValue('原始标题');
 await page.getByRole('button',{name:'编辑',exact:true}).click();await title.fill('已保存的新标题');await page.getByRole('button',{name:'保存并退出',exact:true}).click();await expect(title).toHaveAttribute('readonly','');await expect(title).toHaveValue('已保存的新标题');
 await page.getByRole('button',{name:'编辑',exact:true}).click();await title.fill('不应丢失的草稿');page.once('dialog',d=>d.dismiss());await nav().getByRole('button',{name:'文献库',exact:true}).click();await expect(title).toHaveValue('不应丢失的草稿');await page.getByRole('button',{name:'取消编辑',exact:true}).click();
 await page.getByRole('button',{name:'编辑',exact:true}).click();await page.getByRole('button',{name:'恢复原始大纲',exact:true}).click();await page.getByRole('button',{name:'确认',exact:true}).click();await expect(title).toHaveValue('原始标题');
 await page.getByRole('button',{name:'新建综述工作区',exact:true}).click();await page.getByRole('textbox',{name:'综述工作区名称',exact:true}).fill('Imported'+Date.now());await page.getByRole('combobox',{name:'综述框架来源'}).click();await page.getByRole('option',{name:'来自文件',exact:true}).click();
 await page.getByLabel('选择综述 CSV').setInputFiles({name:'bad.csv',mimeType:'text/csv',buffer:Buffer.from('Serial,Title\n1.1,Missing parent')});await expect(page.getByRole('alert').last()).toContainText('缺少父标题');await expect(page.getByRole('button',{name:'创建工作区',exact:true})).toBeDisabled();
 await page.getByLabel('选择综述 CSV').setInputFiles({name:'中文框架.csv',mimeType:'text/csv',buffer:Buffer.from('\ufeffSerial,Title\r\n1,导入标题\r\n1.1,导入子标题\r\n')});await expect(page.getByText('中文框架.csv · 校验通过 · 2 个标题')).toBeVisible();await page.getByRole('button',{name:'创建工作区',exact:true}).click();await expect(title).toHaveValue('导入标题');await expect(title).toHaveAttribute('readonly','');await expect(page.getByRole('dialog')).toHaveCount(0);
 await mkdir('tmp/workspace-ui-screenshots',{recursive:true});await page.screenshot({path:'tmp/workspace-ui-screenshots/review.png',fullPage:true});
 await nav().getByRole('button',{name:'文献库',exact:true}).click();const cards=page.locator('.preparation-card');await expect(cards).toHaveCount(4);await expect(page.getByRole('button',{name:'一键更新文献',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'一键更新文献',exact:true}).click();expect(mutations.at(-1).action).toBe('library.start');await cards.nth(1).getByRole('button',{name:'下载',exact:true}).click();expect(mutations.at(-1).action).toBe('download.start');
 await cards.nth(2).getByRole('button',{name:'执行转化',exact:true}).click();expect(mutations.at(-1).action).toBe('markdown.start');
 await cards.nth(3).getByRole('button',{name:'建立 / 更新索引',exact:true}).click();expect(mutations.at(-1).action).toBe('vector.start');
 await cards.nth(3).locator('summary').click();await cards.nth(3).getByRole('button',{name:'清空全部索引数据',exact:true}).click();await expect(page.getByText('XML、检索式、笔记、已有综述', {exact:false})).toBeVisible();await page.getByRole('button',{name:'确认执行',exact:true}).click();expect(mutations.at(-1).action).toBe('library.clear');expect(mutations.at(-1).args.scope).toBe('index');
 await cards.nth(3).locator('summary').click();await page.screenshot({path:'tmp/workspace-ui-screenshots/library.png',fullPage:true});
 await page.getByRole('button',{name:'浏览文本块 / 检索测试'}).click();await expect(page.locator('.chunk-article strong')).toBeVisible();await page.getByRole('combobox',{name:'选择文献'}).click();await page.getByRole('option').filter({hasText:'2 · Abstract paper'}).click();await page.getByRole('button',{name:'查看 metadata',exact:true}).click();await expect(page.getByRole('button',{name:'复制完整 metadata',exact:true})).toBeVisible();await page.screenshot({path:'tmp/workspace-ui-screenshots/metadata.png',fullPage:true});await page.getByRole('button',{name:'关闭弹窗'}).click();
 await page.setViewportSize({width:1100,height:850});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:'tmp/workspace-ui-screenshots/library-narrow.png',fullPage:true});
 expect(errors).toEqual([]);console.log(JSON.stringify({success:true,checks:['navigation order','current project overview','read-only default','save and cancel editing','navigation guard','restore original','CSV invalid/valid file chooser','new workspace read-only','four independent action routes','scoped clear confirmation','complete metadata detail','responsive layout','no React errors']}));
}catch(e){await page.screenshot({path:'tmp/workspace-ui-screenshots/failure.png',fullPage:true});throw e;}finally{await browser.close();server.kill();await new Promise(resolve=>server.once('exit',resolve));await rm(fixture,{recursive:true,force:true});}
