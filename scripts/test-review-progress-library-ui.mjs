import {chromium,expect} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1600,height:1080}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
let mockBatch=false, mockMissing=false;
await page.route('**/__prototype/state',async route=>{if(route.request().method()==='PUT')return route.fulfill({json:{ok:true}});const r=await route.fetch();const s=await r.json();s.active='gut';await route.fulfill({json:s});});
await page.route('**/__research',async route=>{
 const req=route.request().postDataJSON();
 // Read-only against the real project. Never submit a generation/download request.
 if(!['get','review.get','review.list','review.writing.status','review.writing.section','review.writing.preview','download.status','markdown.status','vector.status','status'].includes(req.action)&&/start|retry|save|stop|cancel|reconcile/.test(req.action))throw Error('Unexpected mutation '+req.action);
 const r=await route.fetch();const data=await r.json();
 if(req.action==='review.writing.status'&&data.ok){
  if(mockBatch){data.data.latest=24;data.data.job={...data.data.job,state:'partial',mode:'write',total:45,completed:24,failed:20,pending:1,running:0,cancelled:0,settled:44};data.data.units=data.data.units.map((u,i)=>({...u,state:i<20?'failed':u.state,latest:i>=20}));}
  if(mockMissing){data.data.fileRevision='external-delete';data.data.units=data.data.units.map(u=>({...u,revision:'missing',hasContent:false,latest:false}));}
 }
 if(req.action==='review.writing.section'&&mockMissing)data.data={sections:[],evidence:{}};
 await route.fulfill({json:data});
});
try{
 await page.goto('http://127.0.0.1:1420');
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'文献库',exact:true}).click();
 const cards=page.locator('.preparation-card');await expect(cards).toHaveCount(4);
 await expect(cards.nth(3)).toContainText('/ 105 篇已索引',{timeout:10000});await expect(cards.nth(1)).toContainText('20 篇摘要');await expect(cards.nth(1)).toContainText('最新');
 await expect(cards.nth(1).getByRole('button',{name:'下载',exact:true})).toBeEnabled();
 await expect(cards.nth(1).getByRole('button',{name:'更新',exact:true})).toBeEnabled();
 await expect(cards.nth(2).getByRole('button',{name:'执行转化'})).toBeVisible();
 const sizes=await cards.evaluateAll(nodes=>nodes.map(n=>({w:n.getBoundingClientRect().width,h:n.getBoundingClientRect().height})));
 expect(Math.max(...sizes.map(s=>s.w))-Math.min(...sizes.map(s=>s.w))).toBeLessThan(2);
 expect(Math.max(...sizes.map(s=>s.h))-Math.min(...sizes.map(s=>s.h))).toBeLessThan(2);
 await mkdir('docs/screenshots',{recursive:true});await page.screenshot({path:'docs/screenshots/library-preparation.png',fullPage:true});
 await page.setViewportSize({width:1100,height:900});await page.screenshot({path:'docs/screenshots/library-preparation-narrow.png',fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.setViewportSize({width:1600,height:1080});
 await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'综述工作台',exact:true}).click();
 await page.getByRole('tab',{name:'综述撰写',exact:true}).click();
 await expect(page.locator('.writing-progress')).toContainText('45 / 45');
 await page.locator('.writing-setup .review-extra summary').click();await expect(page.getByRole('checkbox',{name:'启用单次请求字符预算（可选）'})).not.toBeChecked();await expect(page.getByLabel('单次请求字符预算',{exact:true})).toHaveCount(0);
 await page.locator('.writing-setup .review-extra summary').click();
 await page.screenshot({path:'docs/screenshots/review-progress.png',fullPage:true});
 mockBatch=true;
 await expect(page.getByRole('button',{name:'重试失败项 · 20'})).toBeVisible({timeout:10000});
 await expect(page.locator('.writing-batch-counts')).toContainText('成功 24');await expect(page.locator('.writing-batch-counts')).toContainText('待处理 1');
 await expect(page.getByRole('progressbar',{name:'综述批次处理进度'})).toHaveAttribute('value','44');
 await page.screenshot({path:'docs/screenshots/review-progress-failures.png',fullPage:true});
 const tree=page.getByRole('navigation',{name:'撰写章节'});await tree.getByRole('button').filter({hasText:'1.1.1'}).first().click();
 await expect(page.locator('.writing-markdown')).toContainText('肠道菌群');mockMissing=true;
 await expect(page.locator('.writing-markdown')).toHaveCount(0,{timeout:10000});
 await page.setViewportSize({width:1100,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:'docs/screenshots/review-progress-narrow.png',fullPage:true});
 expect(errors).toEqual([]);console.log(JSON.stringify({success:true,cards:sizes,checks:['equal preparation cards','abstract fallback after attempted download','separate download refresh convert actions','budget off by default','idle polling','distinct batch counters','explicit retry failures','external-file change refreshes open body','responsive without page overflow','no page errors']}));
}catch(e){console.error(e);await page.screenshot({path:'tmp/review-ui-failure.png',fullPage:true});throw e;}finally{await page.unrouteAll({behavior:'ignoreErrors'});await browser.close();}
