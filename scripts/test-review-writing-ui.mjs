import {chromium,expect} from '@playwright/test';
import {mkdir,readFile} from 'node:fs/promises';
const saved=JSON.parse(await readFile('workspace/gut/review/test1/writing-settings.json','utf8')); 
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1600,height:1080}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
// Browser persistence is isolated; real review reads use the app's own bridge.
await page.route('**/__prototype/state',async route=>{if(route.request().method()==='PUT')return route.fulfill({json:{ok:true}});const response=await route.fetch();const state=await response.json();if(state)state.active='gut';await route.fulfill({json:state});});
try{
 await page.goto('http://127.0.0.1:1420');
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'综述工作台',exact:true}).click();
 await expect(page.getByRole('tab',{name:'综述大纲',exact:true})).toBeVisible();
 await expect(page.getByRole('combobox',{name:'大纲版本'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'新建版本',exact:true})).toHaveCount(0);
 await page.getByRole('tab',{name:'综述撰写',exact:true}).click();
 await expect(page.getByLabel('撰写并发数')).toHaveValue(String(saved.concurrency??3));
 await expect(page.getByLabel('每节文本块数量')).toHaveValue(String(saved.topK??7));
 await expect(page.getByRole('navigation',{name:'撰写章节'})).toBeVisible();
 await expect(page.getByRole('button',{name:'1 · 准备综述提示词'})).toBeVisible();
 await expect(page.getByRole('button',{name:'2 · 生成综述'})).toBeDisabled();
 expect(await page.getByLabel('撰写并发数').getAttribute('max')).toBeNull();
 await expect(page.getByLabel('初筛候选数量')).toHaveCount(0);
 const tree=page.getByRole('navigation',{name:'撰写章节'});const count=await tree.getByRole('button').count();expect(count).toBeGreaterThan(100);
 await tree.getByRole('button').filter({hasText:'1.1.1'}).first().click();
 await expect(page.locator('.writing-body-toolbar h3')).toContainText('1.1.1');
 await page.getByRole('button',{name:'全文预览',exact:true}).click();
 
 await expect(page.locator('.writing-markdown')).toContainText('参考文献');
 await tree.getByRole('button').nth(4).click();
 await page.locator('.review-page-heading').scrollIntoViewIfNeeded();
 await mkdir('docs/screenshots',{recursive:true});await page.screenshot({path:'docs/screenshots/review-writing.png',fullPage:true});
 await page.setViewportSize({width:1100,height:900});
 await page.locator('.review-page-heading').scrollIntoViewIfNeeded();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
 await page.screenshot({path:'docs/screenshots/review-writing-narrow.png',fullPage:true});
 await page.getByRole('tab',{name:'综述大纲',exact:true}).click();
 await expect(page.getByLabel('综述主题',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'设置',exact:true}).first().click();
 await page.getByRole('button',{name:'召回与重排',exact:true}).click();
 await expect(page.getByLabel('重排模型')).toBeVisible();
 await expect(page.getByLabel('召回候选数量')).toHaveValue('50');
 await expect(page.getByText('不重排 · 默认',{exact:true})).toBeVisible();
 await page.screenshot({path:'docs/screenshots/retrieval-settings.png',fullPage:true});
 expect(errors).toEqual([]);
 console.log(JSON.stringify({success:true,outlineNodes:count,checks:['real existing project workspace migration','outline/writing tabs','no version controls','saved writing parameters preserved; no concurrency cap','full mixed-depth outline tree','preview','responsive width','no browser errors']}));
}finally{await browser.close();}
