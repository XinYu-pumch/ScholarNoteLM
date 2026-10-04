/** Actual writing component and standalone exporter; isolated data, no APIs. */
import {chromium,expect} from '@playwright/test';
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const root=process.cwd(),tmp=await mkdtemp(path.join(root,'tmp/shared-pool-ui-')),out=path.join(root,'experiments/review2-shared-pool');let server,browser;
try{
 await mkdir(out,{recursive:true});
 await writeFile(path.join(tmp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
 await writeFile(path.join(tmp,'main.jsx'),`import React from 'react';import {createRoot} from 'react-dom/client';import ReviewWriting from '/@fs/${root}/apps/desktop/src/ReviewWriting.tsx';${['styles','workbench','review','readability','refinements'].map(n=>`import '/@fs/${root}/apps/desktop/src/${n}.css';`).join('')}
window.calls=[];
const rows=[{id:'parent',serial:'1',title:'联合写作单元'},{id:'a',serial:'1.1',title:'遗传特征'},{id:'b',serial:'1.2',title:'临床结局'}];
const resources=[{id:'table',kind:'table',pmid:'23456789',documentVersion:'v',lineStart:10,lineEnd:12,content:'| Gene | Value |\\n|---|---|\\n| ABC | 42 |',context:[]}];
const first={id:'chunk1',evidenceId:'E1',retrievedFor:['1.1'],text:'当前小节检索到的原文。',metadata:{pmid:'12345678',title:'第一篇文献',sourceKind:'fulltext',sectionPath:[]},resources:[]};
const second={id:'chunk2',evidenceId:'E2',retrievedFor:['1.2'],text:'兄弟小节检索到、可共享引用的原文。',metadata:{pmid:'23456789',title:'第二篇文献',sourceKind:'fulltext',sectionPath:[]},resources};
window.fixture={status:{fileRevision:'1',config:{concurrency:3,topK:7,language:'中文',requirements:'',profileId:'',contextChars:90000,limitContext:false},rows,units:[{id:'parent',serial:'1',title:'联合写作单元',nodes:['parent','a','b'],leafIds:['a','b'],state:'latest',latest:true,promptReady:true,hasContent:true,revision:'1'}],job:{state:'done'},latest:1,total:1,model:'fixture',prepared:1,runtimeReady:true,retrieval:{config:{method:'bm25',reranker:'none'},apiVerified:true},effectiveCandidateK:7},section:{sections:[{node_id:'parent',markdown:'导语'},{node_id:'a',markdown:'使用共享证据 (PMID: 23456789)。\\n\\n| Finding | Source |\\n|---|---|\\n| A | PMID: 23456789 |'},{node_id:'b',markdown:'其他结论'}],evidence:{a:{query:'遗传特征',chunks:[first]},b:{query:'临床结局',chunks:[second]}},sharedEvidence:[first,second]}};
const siblingAnchor='obj_bbbbbbbbbbbbbbbbbbbbbbbb';
const bodyBlocks=[{type:'markdown',text:'使用共享证据 (PMID: 23456789)，见 [表 1](#obj_aaaaaaaaaaaaaaaaaaaaaaaa) 及同级小节的 [表 3](#'+siblingAnchor+')。'},
{type:'table',anchor:'obj_aaaaaaaaaaaaaaaaaaaaaaaa',label:'表 1',title:'跨来源比较',html:'<table><thead><tr><th>Finding</th><th>Source</th></tr></thead><tbody><tr><td>A</td><td>PMID: 23456789</td></tr></tbody></table>',notes:'人群不同，保留来源。'},
{type:'resource',resourceId:'original-table',kind:'table',label:'表 2',pmid:'23456789',html:'<table><tbody><tr><th>Original</th></tr><tr><td>42</td></tr></tbody></table>'},
{type:'resource',resourceId:'original-image',kind:'figure',label:'图 1',pmid:'23456789',dataUrl:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII='}];
window.fixture.section.sections[1].displayBlocks=bodyBlocks;window.fixture.preview={markdown:'Preview',displayBlocks:[...bodyBlocks,{type:'table',anchor:siblingAnchor,label:'表 3',title:'同级小节结果',html:'<table><tr><td>Other result</td></tr></table>',notes:''}]};
createRoot(document.getElementById('root')).render(<div style={{padding:24}}><ReviewWriting projectId="fixture" name="review" visible={true} outlineRevision={1} outlineBusy={false} onActive={()=>{}}/></div>);`);
 server=await createServer({configFile:false,root:tmp,cacheDir:path.join(tmp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','@tauri-apps/api/core','react-markdown','remark-gfm']},server:{host:'127.0.0.1',port:0,fs:{allow:[root]}},plugins:[{name:'isolated-rpc',enforce:'pre',resolveId(src,importer){if(importer?.endsWith('/ReviewWriting.tsx')||importer?.endsWith('/EvidenceResources.tsx')){if(src==='./context')return '\0ctx';if(src==='./research-api')return '\0rpc';}},load(id){if(id==='\0ctx')return 'export function useApp(){return {notify:()=>{},openSettings:()=>{}}}';if(id==='\0rpc')return `export const message=e=>String(e);export async function rpc(action,args){window.calls.push(action);if(action==='review.writing.status')return structuredClone(window.fixture.status);if(action==='review.writing.section')return structuredClone(window.fixture.section);if(action==='review.writing.preview')return structuredClone(window.fixture.preview);throw Error('Unexpected request '+action)}`;}}]});await server.listen();
 browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:'+server.httpServer.address().port);
 await page.getByRole('navigation',{name:'撰写章节'}).getByRole('button').filter({hasText:'1.1'}).click();
 await expect(page.locator('.writing-markdown table')).toHaveCount(2);await expect(page.locator('.writing-evidence>h4')).toContainText('本单元共享证据');
 await expect(page.locator('.writing-evidence-card')).toHaveCount(2);await page.locator('.writing-evidence-card summary').nth(1).click();
 await expect(page.locator('.writing-evidence-card').nth(1)).toContainText('来源小节 1.2');
 await page.locator('.evidence-resource>summary').click();await expect(page.locator('.resource-table')).toContainText('42');
 await expect(page.locator('.writing-prompt-note')).toContainText('prompt_section_*.json');
 await expect(page.locator('.writing-markdown .body-resource')).toHaveCount(2);await expect(page.locator('.writing-markdown img')).toHaveCount(1);
 await page.locator('.writing-markdown a').filter({hasText:'表 1'}).click();await expect(page.locator('#obj_aaaaaaaaaaaaaaaaaaaaaaaa')).toBeInViewport();
 await page.locator('.writing-markdown a').filter({hasText:'表 3'}).click();await expect(page.locator('#obj_bbbbbbbbbbbbbbbbbbbbbbbb')).toBeInViewport();
 await page.getByRole('button',{name:'全文预览',exact:true}).click();await expect(page.locator('.writing-body h3')).toContainText('完整综述预览');await expect(page.locator('.writing-markdown .body-resource')).toHaveCount(2);
 await page.screenshot({path:path.join(out,'shared-pool-ui.png'),fullPage:true});
 await page.setViewportSize({width:1100,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 expect(await page.evaluate(()=>window.calls.every(a=>['review.writing.status','review.writing.section','review.writing.preview'].includes(a)))).toBe(true);
 // Export actual structured resources and verify the offline reader.
 execFileSync(path.join(root,'runtimes/downloader/bin/python'),['-c',`
import sys
from pathlib import Path
sys.path[:0]=['services/downloader','services/downloader/tests']
from test_review_bundle import BundleTests
import review_export,review_content,review_bundle
t=BundleTests();t.setUp()
try:
 refs={'1.1':{'12345678':[review_export.reference_entry(t.first,t.project,set())]}}
 body={'1.1':'Shared evidence (PMID: 12345678)\\n\\n| Finding | Source |\\n|---|---|\\n| A | (PMID: 12345678) |'}
 value=t.output();value['sections'][1]['blocks']=[{'type':'markdown','text':'See {{ref:T1}} and {{ref:R1}} [E1].'}, {'type':'table','table_id':'T1','title':'Synthesis','columns':['Finding','Source'],'rows':[['A','[E1] [R1]']],'notes':'Different populations [E1].'},{'type':'resource','resource_id':'R1'},{'type':'resource','resource_id':'R2'}]
 sections,errors=review_bundle.decode(value,t.write(),t.unit,{'model':'vision','visionModels':['vision']});assert not errors
 rendered=review_content.render_sections(sections,t.bundle['resources'],t.project)
 body={n['serial']:r['markdown'] for n,r in zip(t.nodes,rendered)};blocks={n['serial']:r['displayBlocks'] for n,r in zip(t.nodes,rendered)}
 Path(sys.argv[1]).write_text(review_export.html_document('Shared pool export',t.nodes,body,refs,False,blocks))
finally:t.tearDown()
`,path.join(out,'shared-pool-export.html')],{cwd:root});
 await page.goto('file://'+path.join(out,'shared-pool-export.html'));await page.locator('.lnk').first().click();
 await expect(page.locator('.content table')).toHaveCount(2);await expect(page.locator('#area .source-resource')).toHaveCount(2);
 await page.locator('#area .source-resource>summary').first().click();await expect(page.locator('#area .source-resource-content table')).toContainText('42');
 await page.locator('#area .source-resource>summary').nth(1).click();await expect(page.locator('#area img')).toHaveCount(1);expect(await page.locator('#area img').evaluate(el=>el.complete&&el.naturalWidth>0)).toBe(true);
 await expect(page.locator('.content .body-resource')).toHaveCount(2);expect(await page.locator('.content img').evaluate(el=>el.complete&&el.naturalWidth>0)).toBe(true);
 await page.locator('#ref [data-close="ref"]').click();
 const objectLinks=page.locator('.content a[href^="#obj_"]');await expect(objectLinks).toHaveCount(2);await objectLinks.first().click();const target=await objectLinks.first().getAttribute('href');await expect(page.locator(target)).toBeInViewport();
 await page.setViewportSize({width:1500,height:1000});await page.screenshot({path:path.join(out,'shared-pool-export.png')});
 expect(errors).toEqual([]);console.log(JSON.stringify({passed:true,checks:['shared sibling evidence visible','retrieval provenance preserved','body and evidence tables rendered','canonical JSON shown','offline export includes whole table and image','no generation requests','no browser errors']}));
}finally{await browser?.close();await server?.close();await rm(tmp,{recursive:true,force:true});}
