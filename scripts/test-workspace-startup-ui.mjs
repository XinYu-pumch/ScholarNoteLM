// Starts an isolated backend; never connects to an existing development server.
import {chromium,expect} from '@playwright/test';
import {mkdtemp,mkdir,symlink,readFile,writeFile,access,rm} from 'node:fs/promises';
import {spawn,spawnSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd();const testRoot=await mkdtemp(path.join(root,'tmp/workspace-onboarding-'));
for(const name of ['services','runtimes'])await symlink(path.join(root,name),path.join(testRoot,name),'dir');
await mkdir(path.join(testRoot,'tmp'));
const configured=spawnSync(path.join(root,'cache/tauri-target/debug/research-cli'),[],{env:{...process.env,SCHOLARNOTELM_ROOT:testRoot},input:JSON.stringify({action:'mesh.settings',args:{autoUpdate:false,includeScr:false}}),encoding:'utf8'});
if(!JSON.parse(configured.stdout).ok)throw Error('Cannot configure isolated fixture');
const vite=spawn(path.join(root,'runtimes/node/bin/node'),['node_modules/vite/bin/vite.js','--config','apps/desktop/vite.config.ts','--port','1439'],{cwd:root,env:{...process.env,SCHOLARNOTELM_ROOT:testRoot},stdio:'ignore'});
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1100,height:760},locale:'zh-CN'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:1439')).ok)break;}catch{}await new Promise(r=>setTimeout(r,200));}
 await page.goto('http://127.0.0.1:1439');await expect(page.getByRole('heading',{name:'选择研究工作目录'})).toBeVisible();
 let defaultExists=true;try{await access(path.join(testRoot,'workspace'));}catch{defaultExists=false;}expect(defaultExists).toBe(false);
 await page.getByLabel('工作目录',{exact:true}).fill('relative');await page.getByRole('button',{name:'使用此目录'}).click();await expect(page.getByRole('alert')).toContainText('绝对路径');
 const folder=path.join(testRoot,'研究 文件夹');await mkdir(folder);await writeFile(path.join(folder,'keep.txt'),'keep');
 await page.getByLabel('工作目录',{exact:true}).fill(folder);
 await page.screenshot({path:path.join(root,'tmp/source-release/onboarding.png')});
 await page.getByRole('button',{name:'使用此目录'}).click();await expect(page.getByRole('heading',{name:'选择研究工作目录'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'创建新项目',exact:true}).first()).toBeVisible();
 await page.reload();await expect(page.getByRole('button',{name:'创建新项目',exact:true}).first()).toBeVisible();
 expect(await readFile(path.join(folder,'keep.txt'),'utf8')).toBe('keep');
 const cfg=JSON.parse(await readFile(path.join(testRoot,'config/storage.json'),'utf8'));expect(cfg.workspace).toBe(folder);
 expect(errors).toEqual([]);console.log('First launch, invalid path, Unicode/space path, preservation and restart checks passed.');
}finally{await browser.close();vite.kill('SIGTERM');await new Promise(resolve=>vite.once('exit',resolve));await rm(testRoot,{recursive:true,force:true});}
