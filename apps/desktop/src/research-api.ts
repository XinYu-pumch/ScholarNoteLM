import {forgetPage} from './page-memory';
import {read,queryKey,invalidate} from './query-cache';
export {peek as peekRpc} from './query-cache';
import { Channel, invoke, isTauri } from '@tauri-apps/api/core';
import type { Paper } from './data';
export type Filters={start:string;end:string;sort:string;mode:string;limit:number;jcr:boolean;quartiles:string[];unknown:string};
export type Run={zotero?:{job:string;collection:{key:string;path:string};selectedCollections?:{key:string;name:string;path:string}[]};qualified?:number;target?:number;exhausted?:boolean;candidateLimitReached?:boolean;id:string;revision:number;created:number;count:number;fetched:number;truncated:boolean;translation:string;warnings:unknown;text:string;xmlPath:string};
export type Query={zoteroJob?:import('./ZoteroImport').ZoteroJob;id:string;name:string;text:string;source:string;revision:number;enabled:boolean;archived:boolean;stale?:boolean;error:string;filters:Filters;xmlExists?:boolean;run?:Run};
export type CorpusPaper=Paper & {pmid:string;doi:string;pmcid:string;included:boolean;reason:string;sources:{id:string;name:string;run:string}[];jcr:{journal:string;category:string;quartile:string;jif:string}[]};
export type MeshTerm={id:string;label:string;kind:string;scope:string;terms:string[];trees:string[]};
export type Probe={count?:number;translation?:string;warnings?:unknown;errors?:unknown;error?:string;checked?:number;mesh?:{term:string;verified:boolean}[];samples?:CorpusPaper[]};
export type Proposal={id:string;name:string;text:string;purpose:string;probe?:Probe;meshCheck?:{term:string;verified:boolean}[]};
export type ChatMessage={modelLabel?:string;role:string;text:string;reasoning?:string;error?:string;cancelled?:boolean;created:number;result?:{queries:Proposal[];meshVersion:string;model:string;modelLabel?:string}};
export type WorkbenchData={sourceBusy?:boolean;queries:Query[];chats:ChatThread[];corpus:{snapshot:string;papers:CorpusPaper[];included:number;excluded:number;path:string}};
export type Profile={visionModels?:string[];id:string;name:string;baseUrl:string;model:string;models?:string[];apiKey?:string;hasKey?:boolean;clearKey?:boolean;temperature:number|null;timeout:number};
export type MeshStatus={version:string;year?:number;records:number;terms:number;counts?:Record<string,number>;built?:number;checked?:number;autoUpdate:boolean;includeScr?:boolean;includeScrPreference?:boolean;running:boolean;job?:{state:string;message:string}};
export type SettingsData={profiles:Profile[];activeProfile:string;jcr:{name:string;version:string;rows:number;columns:string[];warnings:string[];warningCount:number}|null;mesh:MeshStatus;pubmed:{email?:string;hasKey:boolean}};
async function transport<T>(action:string,args:Record<string,unknown>={}):Promise<T>{
  if(isTauri()) return invoke<T>('research_rpc',{request:{action,args}});
  const r=await fetch('/__research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,args})});
  const result=await r.json();if(!r.ok||!result.ok)throw new Error(result.error||'研究服务暂时不可用');return result.data;
}
const cachedReads=new Set(['zotero.status','workspace','download.list','markdown.status','vector.status','vector.progress','library.status','library.overview','settings','profile.list','vector.settings','mesh.status','review.list','review.get','review.writing.activity','review.writing.status','review.writing.section','qa.list','qa.get','qa.inventory','qa.settings','chat.list','chat.get']);
const materialReads=['workspace','markdown.status','vector.status','library.overview','qa.inventory','review.list','review.writing.status'];
const materialVersions=new Map<string,string>();
function observeMaterials(action:string,args:Record<string,unknown>,data:unknown){
 if(!['download.list','markdown.status','vector.status','library.status'].includes(action))return;
 const value=data as Record<string,any>;
 const version=JSON.stringify(action==='download.list'
  ?[value.batches?.map((b:any)=>[b.id,b.state,b.counts,b.markdownFollowup]),Object.values(value.assets||{}).map((a:any)=>[a.pmid,a.sha256,a.exists])]
  :[value.job?.id,value.job?.state,value.job?.completed,value.config,value.items,value.cleared]);
 const key=queryKey(action,args),previous=materialVersions.get(key);materialVersions.set(key,version);
 while(materialVersions.size>80)materialVersions.delete(materialVersions.keys().next().value!);
 if(previous!==undefined&&previous!==version)invalidate(typeof args.project==='string'?args.project:undefined,
  ['markdown.status','vector.status','library.overview','qa.inventory','review.writing.status'].filter(v=>v!==action));
}
export async function rpc<T>(action:string,args:Record<string,unknown>={}):Promise<T>{
 if(cachedReads.has(action))return read(queryKey(action,args),async()=>{const value=await transport<T>(action,args);observeMaterials(action,args,value);return value;},action==='profile.list'?500:80);
 const result=await transport<T>(action,args);
 if(/^zotero\.(start|cancel)$/.test(action))invalidate(typeof args.project==='string'?args.project:undefined,['workspace','zotero.status']);
 if(/^(query\.|jcr\.|library\.(start|clear)|markdown\.(start|reconcile|settings.save)|vector\.(start|settings.save|profile.activate|profile.delete)|storage\.)/.test(action))invalidate(typeof args.project==='string'?args.project:undefined,materialReads);
 if(/^(profile\.(save|delete)|pubmed.save)$/.test(action))invalidate(undefined,['profile.list','settings','review.list','review.writing.status']);
 if(/^(qa|chat)\.(new|rename|copy|fork|start|cancel|resume|regenerate|delete|delete_many|archive|archive_many)$/.test(action))invalidate(typeof args.project==='string'?args.project:undefined,[action.startsWith('qa.')?'qa.list':'chat.list',action.startsWith('qa.')?'qa.get':'chat.get'],/\.(delete|archive)(_many)?$/.test(action));
 if(action==='download.settings.save')invalidate(undefined,['markdown.status']);
 if(action==='qa.settings.save')invalidate(undefined,['qa.settings']);
 if(action.startsWith('review.'))invalidate(typeof args.project==='string'?args.project:undefined,['review.list','review.get','review.writing.activity','review.writing.status','review.writing.section']);
 if(action==='storage.delete'){invalidate(String(args.project),undefined,true);forgetPage(String(args.project));}
 return result;
}
if(typeof window!=='undefined'){
 window.addEventListener('research-changed',()=>invalidate(undefined,['workspace','profile.list','settings',...materialReads]));
 window.addEventListener('downloads-changed',()=>invalidate(undefined,['download.list','library.status',...materialReads]));
}

export function changed(){window.dispatchEvent(new Event('research-changed'));}
export function stamp(v?:number){return v?new Date(v*1000).toLocaleString('zh-CN',{hour12:false}):'尚未执行';}
export function message(e:unknown){return e instanceof Error?e.message:String(e);}
export async function exportXml(project:string,run?:string){const result=await rpc<{path:string;content:string}>('xml.export',{project,run});if(!isTauri()){const url=URL.createObjectURL(new Blob([result.content],{type:'application/xml'}));const a=document.createElement('a');a.href=url;a.download=run?'query-pubmed.xml':'pubmed.xml';a.click();URL.revokeObjectURL(url);}return result.path;}

export type ChatThread={id:string;name:string;parentId?:string;created:number;messages?:ChatMessage[]};
export const defaultFilters=():Filters=>({start:'',end:'',sort:'relevance',mode:'explore',limit:30,jcr:false,quartiles:[],unknown:'exclude'});
export type StreamEvent={type:string;text?:string;reasoning?:string;emittedAt?:number};
export async function streamChat(args:Record<string,unknown>,onEvent:(event:StreamEvent)=>void):Promise<ChatMessage[]>{
 const request={action:'chat',args};
 if(isTauri()){const channel=new Channel<StreamEvent>();channel.onmessage=onEvent;return invoke('research_stream',{request,channel});}
 const response=await fetch('/__research/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
 if(!response.ok||!response.body)throw new Error('聊天连接失败');
 const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';let result:ChatMessage[]|undefined;
 const consume=(line:string)=>{if(!line.trim())return;const value=JSON.parse(line);if(value.type==='done'){if(!value.ok)throw new Error(value.error);result=value.data;}else onEvent(value);};
 try{for(;;){const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done});let at;while((at=buffer.indexOf('\n'))>=0){consume(buffer.slice(0,at));buffer=buffer.slice(at+1);}if(done){consume(buffer);break;}}}finally{reader.releaseLock();}
 if(!result)throw new Error('聊天连接已中断，请重新打开对话查看已保存内容');return result;
}

/** One bounded subscription; callers reconnect while their run remains active. */
export async function watchQA<T>(args:Record<string,unknown>,onUpdate:(job:T)=>void,signal:AbortSignal):Promise<void>{
 const request={action:'qa.watch',args};let completed=false;
 const consume=(value:{type:string;data?:T;ok?:boolean;error?:string})=>{
  if(signal.aborted)return;
  if(value.type==='qa_update'&&value.data)onUpdate(value.data);
  if(value.type==='done'){completed=true;if(!value.ok)throw new Error(value.error||'过程连接中断');}
 };
 if(isTauri()){const channel=new Channel<Parameters<typeof consume>[0]>();channel.onmessage=consume;await invoke('research_stream',{request,channel});return;}
 const response=await fetch('/__research/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request),signal});
 if(!response.ok||!response.body)throw new Error('过程连接失败');
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
 try{for(;;){const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done});let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);if(line.trim())consume(JSON.parse(line));}if(done){if(buffer.trim())consume(JSON.parse(buffer));break;}}}finally{reader.releaseLock();}
 if(!completed&&!signal.aborted)throw new Error('过程连接已中断，正在重新连接');
}
