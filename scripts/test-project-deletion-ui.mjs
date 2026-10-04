import {chromium,expect} from '@playwright/test';
import {mkdtemp,rm,readdir,readFile,mkdir} from 'node:fs/promises';
import {spawn,spawnSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd(),fixture=await mkdtemp(path.join(root,'tmp/project-delete-ui-'));
const setup=spawnSync(path.join(root,'runtimes/downloader/bin/python'),['scripts/prepare-workspace-ui.py',fixture],{cwd:root,encoding:'utf8'});if(setup.status!==0)throw Error(setup.stderr);
const imported=spawnSync(path.join(root,'cache/tauri-target/debug/research-cli'),[],{cwd:root,env:{...process.env,SCHOLARNOTELM_ROOT:fixture},input:JSON.stringify({action:'xml.import',args:{project:'UITest',name:'fixture.xml',xml:await readFile(path.join(fixture,'workspace/UITest/pubmed/current.xml'),'utf8')}}),encoding:'utf8'});
if(!JSON.parse(imported.stdout).ok)throw Error(imported.stdout);
const port=4176;
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','preview','--config','apps/desktop/vite.config.ts','--host','127.0.0.1','--port',String(port),'--strictPort'],{cwd:root,env:{...process.env,SCHOLARNOTELM_ROOT:fixture},stdio:'ignore'});
let browser;
try{
 let ready=false;for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error('Preview failed');try{await fetch(`http://127.0.0.1:${port}`);ready=true;break;}catch{await new Promise(r=>setTimeout(r,100));}}if(!ready)throw Error('Preview timeout');
 browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1100,height:700}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`http://127.0.0.1:${port}`);await expect(page.locator('.project-switcher')).toContainText('界面验证项目');await expect(page.getByText('我的项目',{exact:true})).toHaveCount(0);
 for(const height of [700,600,450]){
  await page.setViewportSize({width:1100,height});const tasks=page.getByRole('button',{name:'任务中心',exact:true});await tasks.scrollIntoViewIfNeeded();await expect(tasks).toBeInViewport();await tasks.click();await expect(page.locator('.breadcrumbs')).toContainText('任务中心');
 }
 await page.setViewportSize({width:1100,height:700});await page.locator('.project-switcher').click();await page.getByRole('button',{name:'删除当前项目',exact:true}).click();
 await expect(page.getByRole('button',{name:'确认删除项目'})).toBeEnabled();await expect(page.getByRole('dialog').getByRole('textbox')).toHaveCount(0);await expect(page.getByRole('dialog')).toContainText('无法恢复');await page.getByRole('button',{name:'取消',exact:true}).click();
 await page.locator('.project-switcher').click();await page.getByRole('button',{name:'创建新项目',exact:true}).click();await page.getByLabel('项目名称',{exact:true}).fill('另一个项目');await page.getByLabel('项目文件夹名').fill('另一个_项目2026');await page.getByRole('button',{name:'创建项目',exact:true}).click();await expect(page.locator('.project-switcher')).toContainText('另一个项目');
 async function remove(){await page.locator('.project-switcher').click();await page.getByRole('button',{name:'删除当前项目',exact:true}).click();await page.getByRole('button',{name:'确认删除项目'}).click();}
 await remove('另一个项目');await expect(page.locator('.project-switcher')).toContainText('界面验证项目');await page.reload();await expect(page.locator('.project-switcher')).toContainText('界面验证项目');
 await remove('界面验证项目');await expect(page.getByRole('heading',{name:'还没有研究项目'})).toBeVisible();await page.reload();await expect(page.getByRole('heading',{name:'还没有研究项目'})).toBeVisible();
 expect(await readdir(path.join(fixture,'workspace'))).toEqual([]);
 await page.getByRole('button',{name:'创建新项目',exact:true}).click();await page.getByLabel('项目名称',{exact:true}).fill('重新开始');await page.getByLabel('项目文件夹名').fill('Fresh');await page.getByRole('button',{name:'创建项目',exact:true}).click();await expect(page.locator('.project-switcher')).toContainText('重新开始');
 await mkdir('tmp/project-delete-screenshots',{recursive:true});await page.screenshot({path:'tmp/project-delete-screenshots/sidebar.png'});
 expect(errors).toEqual([]);console.log(JSON.stringify({success:true,checks:['no duplicate projects','task access at 700/600/450px','confirmation and cancel','Chinese underscore project folder create and delete','automatic project switch','delete last project','reload empty state','permanent deletion leaves no hidden backup','create after empty state','no React errors']}));
}finally{if(browser)await browser.close();server.kill();await new Promise(resolve=>server.once('exit',resolve));await rm(fixture,{recursive:true,force:true,maxRetries:10,retryDelay:200});}
