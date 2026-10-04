import {chromium,expect} from '@playwright/test';
import {resolve} from 'node:path';
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1500,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('file://'+resolve('tmp/badr-export-check/review.html'));
 await expect(page.locator('#toc .toc-item')).toHaveCount(4);
 await expect(page.locator('#main .sec')).toHaveCount(4);
 const cite=page.locator('.lnk').first();const pmid=await cite.getAttribute('data-pmid');const scope=await cite.getAttribute('data-scope');await cite.click();
 await expect(page.locator('#area .card').first()).toContainText('PMID: '+pmid);
 await expect(page.locator('#area .card').first()).toContainText('来源章节：'+scope);
 await expect(page.locator('#area>a')).toHaveAttribute('href','https://pubmed.ncbi.nlm.nih.gov/'+pmid+'/');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'docs/screenshots/review-badr-html.png'});
 expect(errors).toEqual([]);console.log(JSON.stringify({success:true,checks:['BADR sample section JSON','full heading order','three panels','PMID scoped evidence','PubMed link','no horizontal overflow','no script errors']}));
}finally{await browser.close();}
