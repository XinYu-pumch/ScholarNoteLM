import {chromium,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});
let state=JSON.parse(await readFile('data/prototype/state.json','utf8'));state.theme='light';
await page.route('**/__prototype/state',async route=>{if(route.request().method()==='PUT')state=route.request().postDataJSON();await route.fulfill({json:state});});
await page.goto('http://127.0.0.1:1420');await expect(page.getByRole('button',{name:'新建检索式',exact:true})).toBeVisible();await expect(page.locator('.save-state')).toContainText('已保存到本地');await page.mouse.move(0,0);await page.screenshot({path:'docs/screenshots/workbench-ready.png',animations:'disabled'});
await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'MeSH 本地索引',exact:true}).click();await expect(page.locator('.wb-reference-card')).toContainText('355,232');await expect(page.locator('.settings-nav button.active')).toHaveText('MeSH 本地索引');await expect(page.locator('.save-state')).toContainText('已保存到本地');await page.mouse.move(0,0);await page.screenshot({path:'docs/screenshots/settings-mesh-ready.png',animations:'disabled'});
await browser.close();
