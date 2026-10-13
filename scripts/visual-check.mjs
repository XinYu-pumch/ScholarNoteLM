/** Read-only validator for snapshots gathered through the supported browser UI tools.
 * Create an isolated root with create-design-fixture.py; start Vite with that root.
 * Capture DOM geometry (read-only) and screenshots with CUA, then pass the JSON:
 * node scripts/visual-check.mjs <snapshot.json>
 * No implicit connection to the user's 1420 server and no obsolete overview/save-state assertions.
 */
import assert from 'node:assert/strict';import {readFile,realpath} from 'node:fs/promises';import {resolve,relative} from 'node:path';
const file=process.argv[2];assert.ok(file,'Pass a captured Design System snapshot JSON.');
const report=JSON.parse(await readFile(file,'utf8'));const root=await realpath(report.fixtureRoot);
const tmp=await realpath(new URL('../tmp/',import.meta.url));assert.ok(relative(tmp,root)&&!relative(tmp,root).startsWith('..'),'Only isolated tmp fixtures may be verified.');
await readFile(resolve(root,'.design-system-fixture'),'utf8');
assert.ok(report.views?.length>=6,'Capture desktop dimensions, both themes and a stress viewport.');
for(const view of report.views){
 assert.ok(view.width>0&&view.height>0);assert.ok(['light','dark'].includes(view.theme));
 assert.equal(view.pageOverflow,false,`${view.page} ${view.width}: whole-page overflow`);
 assert.deepEqual(view.unnamedButtons,[],`${view.page}: unnamed controls`);
 assert.equal(view.overviewPresent,false,'Removed overview must not return');
 assert.equal(view.globalSavedText,false,'Global saved status must remain removed');
 if(view.composer)assert.ok(view.composer.width>0&&view.composer.height>0,`${view.page}: composer missing`);
}
for(const size of ['900x650','1024x768','1440x940','360x780'])assert.ok(report.views.some(v=>`${v.width}x${v.height}`===size),`Missing ${size}`);
assert.ok(report.views.some(v=>v.theme==='dark'));assert.ok(report.views.some(v=>v.theme==='light'));
assert.deepEqual(report.consoleErrors,[]);console.log(JSON.stringify({passed:true,views:report.views.length,fixture:relative(tmp,root)}));
