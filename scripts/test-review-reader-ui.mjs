// Standalone/offline HTML reader: navigation, scoped evidence, responsive drawers and print.
import { chromium, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
const output = resolve('tmp/html-reader-check');
mkdirSync(output, { recursive: true });
execFileSync(resolve('runtimes/downloader/bin/python'), ['-c', `
import sys, shutil
from pathlib import Path
sys.path.insert(0, 'services/downloader')
import engine as e, review_manuscripts as manuscripts, html_compaction
rows = [{'serial': s, 'title': t} for s,t in [('1','研究背景'),('1.1','补体调控与遗传因素'),('1.1.1','证据与研究局限'),('1.1.1.1.1.1.1','完整保留七级编号'),('2','临床研究与未来方向')]]
sections = {r['serial']: ('正文用于验证长文阅读与引用定位。 **加粗**与*斜体*。 (PMID: 12345678)\\n\\n' * 8) for r in rows}
sections['2'] += '\\n| 基因 | 研究内容 |\\n| --- | --- |\\n| C3 | 补体调节 |\\n\\n<script>alert(1)</script>'
refs = {r['serial']: {'12345678': ['章节 '+r['serial']+' 的素材。 Gene<sup>2</sup> and H<sub>2</sub>O. <img src=x onerror=alert(1)>']} for r in rows}
image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
entry={'id':'image-evidence','html':'<p>Embedded image evidence</p>','resources':[{'id':'figure','kind':'figure','pmid':'12345678','lineStart':1,'lineEnd':1,'dataUrl':image,'context':[]}]}
refs['2']['12345678'].append(entry)
refs['1.1.1']['12345678'].append(entry)
destination=Path(sys.argv[1]);e.ROOT=destination.parent/'isolated';e.PROJECT='test'
value={'topic':'综述阅读 · 格式与引用验证','rows':rows,'sections':sections,'references':refs,'partial':True,
       'blocks':{r['serial']:[{'type':'markdown','text':sections[r['serial']]}] for r in rows},'pmids':['12345678'],'outlineHash':'fixture','models':[]}
figure={'type':'resource','kind':'figure','resourceId':'figure','label':'图 1','pmid':'12345678','dataUrl':image}
value['blocks']['2'].extend([figure,figure])
value.update(id=manuscripts.payload_hash(value),created=1,label='reader')
manuscripts.store(e,'Review',value)
assert len(list(manuscripts.folder(e,'Review').glob('assets/*.gz')))==1
exported=manuscripts.export(e,'Review','html',value['id'])
html=Path(exported['path']).read_text()
assert html.count(image)==1
stored=html_compaction.parts(html)[1]
assert len(stored['images'])==1 and len(stored['resources'])==1
assert html_compaction.unpack(stored)==refs
shutil.copyfile(exported['path'],destination)
shutil.rmtree(e.ROOT)  # Only the moved HTML remains when the browser opens it.
`, resolve(output, 'review.html')], { cwd: resolve('.'), encoding: 'utf8' });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
const errors = [], requests = [];
page.on('pageerror', e => errors.push(e.message));
page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()); });
try {
 await page.goto('file://' + resolve(output, 'review.html'));
 await expect(page.locator('.sec')).toHaveCount(5);
 await expect(page.locator('h6')).toContainText('1.1.1.1.1.1.1');
 await expect(page.locator('#ref')).toBeHidden();
 await page.locator('.toc-item[data-serial="1"] button').click();
 await expect(page.locator('.toc-item[data-serial="1.1"]')).toBeHidden();
 await expect(page.locator('.toc-item[data-serial="2"]')).toBeVisible();
 await page.locator('.toc-item[data-serial="1"] button').click();
 await expect(page.locator('.toc-item[data-serial="1.1"]')).toBeVisible();
 await page.locator('.toc-item[data-serial="1.1"] a').click();
 await expect(page.locator('.toc-item[data-serial="1.1"] a')).toHaveAttribute('aria-current', 'location');
 await page.locator('.lnk[data-scope="1.1"]').first().click();
 await expect(page.locator('#ref')).toBeVisible();
 await expect(page.locator('#area .cb')).toContainText('章节 1.1 的素材');
 await expect(page.locator('#area sup')).toHaveText('2');
 await expect(page.locator('#area sub')).toHaveText('2');
 await expect(page.locator('#area img')).toHaveCount(0);
 await expect(page.locator('#area>a')).toHaveAttribute('href', 'https://pubmed.ncbi.nlm.nih.gov/12345678/');
 // The same PMID in another section must show that section's evidence.
 await page.locator('.lnk[data-scope="2"]').first().click();
 await expect(page.locator('#area .cb').first()).toContainText('章节 2 的素材');
 await expect(page.locator('#area img')).toHaveCount(1);
 await expect.poll(() => page.locator('#area img').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
 await expect(page.locator('.content img')).toHaveCount(2);
 await page.locator('.content img').first().scrollIntoViewIfNeeded();
 await expect.poll(() => page.locator('.content img').evaluateAll(imgs => imgs.every(img => img.complete && img.naturalWidth > 0))).toBe(true);
 await expect(page.locator('.lnk[aria-pressed="true"]')).toHaveCount(1);
 await page.keyboard.press('Escape');
 await expect(page.locator('#ref')).toBeHidden();
 await page.locator('#toggle-toc').click();
 await expect(page.locator('#toc')).toBeHidden();
 await page.locator('#toggle-toc').click();
 await expect(page.locator('#toc')).toBeVisible();
 await page.evaluate(() => { const el = document.getElementById('main'); el.scrollTo({top: el.scrollHeight, behavior: 'instant'}); });
 await expect(page.locator('#progress-label')).toHaveText('100%');
 await page.screenshot({ path: resolve(output, 'desktop.png') });
 for (const width of [1100, 768, 390, 320]) {
   await page.setViewportSize({ width, height: 844 });
   await page.reload();
   if (width < 800) {
     await expect(page.locator('#toc')).toBeHidden();
     await page.locator('#toggle-toc').click();
     await expect(page.locator('#toc')).toBeVisible();
     await expect(page.locator('#scrim')).toBeVisible();
     await page.locator('.toc-item[data-serial="2"] a').click();
     await expect(page.locator('#toc')).toBeHidden();
   }
   await page.locator('.lnk[data-scope="2"]').first().click();
   await expect(page.locator('#ref')).toHaveAttribute('role', 'dialog');
   await expect(page.locator('#main')).toHaveAttribute('inert', '');
   await expect(page.locator('[data-close="ref"]')).toBeFocused();
   await page.keyboard.press('Shift+Tab');
   await expect(page.locator('#area>a')).toBeFocused();
   await page.keyboard.press('Tab');
   await expect(page.locator('[data-close="ref"]')).toBeFocused();
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
   await page.keyboard.press('Escape');
   await expect(page.locator('#ref')).toBeHidden();
   await expect(page.locator('.lnk[data-scope="2"]').first()).toBeFocused();
   expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
 }
 await page.screenshot({ path: resolve(output, 'mobile.png') });
 await page.emulateMedia({ media: 'print' });
 await expect(page.locator('.reader-bar')).toBeHidden();
 await expect(page.locator('#toc')).toBeHidden();
 await expect(page.locator('#ref')).toBeHidden();
 await expect(page.locator('#main')).toHaveCSS('overflow', 'visible');
 await expect.poll(() => page.locator('.content img').evaluateAll(imgs => imgs.every(img => img.complete && img.naturalWidth > 0))).toBe(true);
 await page.pdf({ path: resolve(output, 'review.pdf'), format: 'A4', printBackground: true });
 expect(errors).toEqual([]);
 expect(requests).toEqual([]);
 console.log(JSON.stringify({success:true, checks:['one embedded image reused across body and references','shared evidence retains section scopes','compact manuscript export','moved HTML with source archive removed','embedded image renders offline','full outline','collapsible directory','active section','scoped citations','safe superscripts','reading progress','desktop/tablet/phone layouts','keyboard focus and Escape','print/PDF images','no external requests','no script errors']}));
} finally { await browser.close(); }
