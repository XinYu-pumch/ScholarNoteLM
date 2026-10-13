/** Render production components against in-memory status fixtures. No RPC or user files. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url),dir=new URL('../apps/desktop/src/',import.meta.url);
const noop=()=>{},Empty=()=>null,Wrapper=({children})=>React.createElement('div',null,children);
let tab='models',stateOverrides=[],stateIndex=0,flow={state:'partial',mode:'update',stages:[{stage:'download',failed:3}]};
const profile={id:'fixture',name:'中文配置名',baseUrl:'http://127.0.0.1:1',model:'model-a',models:['model-a'],visionModels:['model-a']};
const settings={profiles:[profile],activeProfile:'fixture',pubmed:{},mesh:{},jcr:{name:'fixture.xlsx',rows:3,warningCount:2303,warnings:['第 628 行未提供分区','第 1058 行未提供分区']}};
const project={id:'fixture',name:'中文项目',papers:[{id:'PMID-1',title:'中文论文标题',author:'作者',researchManaged:true,status:'pdf',year:2026}]};
const markdown={pdfCount:1,latestCount:0,abstractCount:0,downloadStatus:{latest:true},items:[{pmid:'1',pdf:true,raw:true,ready:false,needsConversion:true}],files:{redundant:0},ready:true};
const vectors={readyDocuments:0,eligibleDocuments:1,configured:true,items:[{pmid:'1',pdfState:'latest',markdownState:'outdated',vectorState:'outdated'}]};
const downloads={batches:[],assets:{}};
const stubs={
 './context':{useApp:()=>({project,state:{theme:'light'},settingsTab:tab,notify:noop})},
 './useQuery':{useQuery:()=>({data:{job:flow},error:''})},
 './useUnsavedChanges':{useUnsavedChanges:Empty},
 './page-memory':{usePageState:(_key,initial)=>[initial,noop]},
 './useTabs':{useTabs:()=>({tab:()=>({}),panel:()=>({})})},
 './research-api':{rpc:()=>{throw Error('Unexpected RPC');},message:String,stamp:String},
 './markdown-api':{useMarkdown:()=>({data:markdown,error:''})},
 './ui':{Modal:Wrapper,Badge:Empty,IconButton:Empty,Empty},
 './ProjectStorage':{ProjectFilesActions:Empty},
 './Select':{default:Wrapper},'./Field':{default:Wrapper},'./StageMenu':{default:Empty},
 './DraftModal':{default:Empty},'./NumberInput':{default:Empty},'./LanguageControls':{},
 './navigation':{},'./LiteratureQA':{},'./Markdown':{},'./ZoteroImport':{ZoteroProgress:Empty},
 './data':{statusLabels:{pdf:'PDF'}},
};
const cache=new Map();
function load(name,overrides={}){
 const file=new URL(name,dir),exports={};
 const compiled=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true,target:ts.ScriptTarget.ES2022}}).outputText;
 vm.runInNewContext(compiled,{exports,require:id=>{
  if(id in overrides)return overrides[id];
  if(id.endsWith('.css'))return {};
  if(id==='react')return {...React,useState:initial=>{const index=stateIndex++;return [index in stateOverrides?stateOverrides[index]:typeof initial==='function'?initial():initial,noop];}};
  if(id==='./locales/en.json')return JSON.parse(fs.readFileSync(new URL('locales/en.json',dir)));
  if(cache.has(id))return cache.get(id);
  if(id in stubs)return {__esModule:true,...stubs[id]};
  if(id.startsWith('./'))return {__esModule:true,default:Empty};
  return require(id);
 },document:{documentElement:{}},localStorage:{getItem:()=>null,setItem:noop},navigator:{language:'zh-CN'},window:{addEventListener:noop}}, {filename:name});
 return exports;
}
const i18n=load('i18n.ts');cache.set('./i18n',i18n);
const download=load('download-api.ts');cache.set('./download-api',{...download,useDownloads:()=>({data:downloads,error:'',item:()=>undefined})});
const vector=load('Vector.tsx');cache.set('./Vector',{...vector,useVectors:()=>({data:vectors,error:''})});
const workflow=load('LiteratureWorkflow.tsx');cache.set('./LiteratureWorkflow',workflow);
const library=load('Library.tsx'),settingsPage=load('ResearchSettings.tsx');
// Task state helpers are actual production code, too.
cache.set('./task-state',load('task-state.ts'));
const taskPage=load('TaskCenter.tsx');
function render(Component,props={},states=[]){stateOverrides=states;stateIndex=0;return renderToStaticMarkup(React.createElement(Component,props));}
function english(html){assert.doesNotMatch(html,/[\u3400-\u9fff]/);}
const props={downloads,markdown,vectors,total:1,error:'',vectorError:''};
i18n.configureLocale('en');
let html=render(workflow.default,props);english(html);assert.match(html,/Download round completed/);assert.match(html,/Get PDFs: 3 papers failed/);
flow={state:'running',mode:'update',stage:'download',stages:[]};html=render(workflow.default,props);english(html);assert.match(html,/Update all · Get PDFs/);
flow=null;
html=render(library.default);assert.match(html,/Converted text needs updating/);assert.match(html,/中文论文标题/);assert.match(html,/作者/);
html=render(taskPage.default);english(html);
downloads.batches.push({id:'download',project:'fixture',state:'done',items:[{pmid:'1',state:'failed',stage:'zotero',progress:{bloomHit:true}}],counts:{failed:1},config:{},created:1});
html=render(taskPage.default,{},{4:true});english(html);assert.match(html,/Finished · Partially incomplete/);

html=render(vector.IndexProgress,{job:{state:'running',pmids:['1'],completed:0,skipped:0,failed:0,adaptiveProgress:{state:'waiting_network',completed:1,total:3},vectorProgress:{completed:1,total:3}}});english(html);
tab='jcr';html=render(settingsPage.default,{},[settings,profile]);english(html);assert.match(html,/2303/);assert.match(html,/Row 628: quartile not provided; Row 1058: quartile not provided/);
tab='models';const states=[settings,profile];states[15]={'model-a:text':{state:'success',seconds:0.1},'model-a:image':{state:'testing'}};
html=render(settingsPage.default,{},states);assert.match(html,/Connection passed · 0.1 seconds/);assert.match(html,/Testing…/);
i18n.configureLocale('zh');html=render(settingsPage.default,{},states);assert.match(html,/连接通过 · 0.1 秒/);assert.match(html,/正在测试…/);
html=render(workflow.default,props);assert.match(html,/本轮下载已完成/);
console.log('PASS: production renders — workflow completion/failures/live stages, artifact labels, tasks, index progress, JCR warnings and model results across locale switches; research titles preserved.');
