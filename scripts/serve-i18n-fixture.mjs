/** Local-only visual fixture. All RPC is mocked; never reads config or user projects.
 * Run: runtimes/node/bin/node scripts/serve-i18n-fixture.mjs
 * Open the printed URL. Stop with Ctrl+C; the temporary directory is removed.
 */
import {createServer} from 'vite';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import path from 'node:path';
const root=process.cwd(),tmp=await mkdtemp(path.join(root,'tmp/i18n-ui-'));
const source='/@fs/'+root+'/apps/desktop/src/';
await writeFile(path.join(tmp,'index.html'),'<div id="root"></div><script type="module" src="/main.jsx"></script>');
await writeFile(path.join(tmp,'main.jsx'),`
import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
import Settings from '${source}ResearchSettings.tsx';import Library from '${source}Library.tsx';import Tasks from '${source}TaskCenter.tsx';
import {configureLocale,useLocale,t} from '${source}i18n.ts';import {LanguageSwitch} from '${source}LanguageControls.tsx';
${['styles','workbench','conversation','panels','design'].map(n=>`import '${source+n}.css';`).join('\n')}
window.fixtureProfile={id:'fixture',name:'Fixture service',baseUrl:'http://127.0.0.1:1/mock-only',model:'deepseek-flash',models:['deepseek-v4-pro','deepseek-flash','a-very-long-model-name-for-layout-testing'],visionModels:['deepseek-flash'],hasKey:false,temperature:null,timeout:10};
window.fixtureProject={id:'fixture',name:'中文项目名保留',papers:[{id:'PMID-1',title:'中文研究内容保持原文',author:'Fixture author',year:2026,researchManaged:true,status:'pdf'}]};
window.fixtureMarkdown={pdfCount:1,latestCount:0,abstractCount:0,downloadStatus:{latest:true},items:[{pmid:'1',pdf:true,raw:true,ready:false,needsConversion:true}],files:{redundant:0},ready:true};
window.fixtureVectors={readyDocuments:0,eligibleDocuments:1,configured:true,items:[{pmid:'1',pdfState:'latest',markdownState:'outdated',vectorState:'outdated'}]};
window.fixtureDownloads={batches:[],assets:{}};window.fixtureCalls=[];
configureLocale('en');
function Demo(){const [mode,show]=useState('settings'),[tab,setTab]=useState('models'),[state,setState]=useState({uiLanguage:'en',theme:'light'});useLocale();window.fixtureContext={project:window.fixtureProject,state,settingsTab:tab,setSettingsTab:setTab,updateState:update=>{const next=update(state);setState(next);configureLocale(next.uiLanguage);},setPage:show,notify:()=>{},openSettings:()=>show('settings')};return <div className="app-shell"><aside className="sidebar"><h2>ScholarNoteLM</h2><p>Isolated UI fixture</p>{[['settings','设置'],['library','文献库'],['tasks','任务中心']].map(([id,label])=><button className="button secondary" key={id} onClick={()=>show(id)}>{t(label)}</button>)}</aside><main className="main-content" style={{height:'100vh',overflow:'auto'}}><header style={{display:'flex',justifyContent:'space-between',padding:16}}><span>ScholarNoteLM · UI verification</span><LanguageSwitch/></header>{mode==='settings'?<Settings/>:mode==='tasks'?<Tasks/>:<Library/>}</main></div>};createRoot(document.getElementById('root')).render(<Demo/>);
`);
const rpc=`export * from '${source}research-api.ts';import {read,queryKey} from '${source}query-cache.ts';export function rpc(action,args={}){return ['library.status','download.list','markdown.status','vector.status','vector.progress'].includes(action)?read(queryKey(action,args),()=>fixtureRpc(action,args),80):fixtureRpc(action,args);}async function fixtureRpc(action,args={}){
window.fixtureCalls.push({action,args});
if(action==='settings')return {profiles:[window.fixtureProfile],activeProfile:'fixture',pubmed:{},mesh:{autoUpdate:false},jcr:{name:'fixture.xlsx',rows:2400,warningCount:2303,warnings:[628,1058,1083,1084,1087,1091,1092,1104].map(i=>'第 '+i+' 行未提供分区')}};
if(action==='llm.test'){await new Promise(r=>setTimeout(r,400));return {reply:'Mock OK',seconds:0.1};}
if(action==='library.status')return {job:{state:'partial',mode:'update',stages:[{stage:'download',failed:3}]}};
if(action==='markdown.status')return window.fixtureMarkdown;
if(action==='download.list')return window.fixtureDownloads;
if(action==='vector.status')return window.fixtureVectors;
if(action==='vector.progress')return {job:null};
if(action==='mesh.status')return {autoUpdate:false};
throw Error('Fixture blocked RPC: '+action);}`;
const server=await createServer({configFile:false,root:tmp,cacheDir:path.join(tmp,'cache'),esbuild:{jsx:'automatic'},optimizeDeps:{include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','@tauri-apps/api/core','react-markdown','remark-gfm']},server:{host:'127.0.0.1',port:1427,strictPort:true,fs:{allow:[root]}},plugins:[{name:'isolated-fixture',enforce:'pre',resolveId(id,importer){if(importer?.startsWith(root+'/apps/desktop/src/')){if(id==='./context')return '\0fixture-context';if(id==='./research-api')return '\0fixture-rpc';}},load(id){if(id==='\0fixture-context')return 'export const useApp=()=>window.fixtureContext;';if(id==='\0fixture-rpc')return rpc;}}]});
await server.listen();console.log('Isolated bilingual fixture: http://127.0.0.1:1427');
for(const signal of ['SIGINT','SIGTERM'])process.once(signal,async()=>{await server.close();await rm(tmp,{recursive:true,force:true});process.exit(0);});
