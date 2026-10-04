import {beginSearchTrace,receiveSearchTrace,endSearchTrace} from './search-stream-diagnostics';
import type {ModelSelection} from './ModelPicker';
import {useSyncExternalStore} from 'react';
import {rpc,streamChat,message,type ChatMessage,type ChatThread} from './research-api';
type Session={project:string;threadId:string;streamId:string;active:boolean;sequence:number;messages:ChatMessage[];error:string};
const sessions=new Map<string,Session>(),listeners=new Set<()=>void>();let revision=0;
const key=(project:string,threadId:string)=>`${project}:${threadId}`;
function changed(){revision++;for(const listener of listeners)listener();}
export function useSearchSessions(){return useSyncExternalStore(callback=>{listeners.add(callback);return()=>listeners.delete(callback);},()=>revision);}
export function searchSession(project:string,threadId?:string){return threadId?sessions.get(key(project,threadId)):undefined;}
export function runningSearchThreads(project:string){return [...sessions.values()].filter(s=>s.project===project&&s.active).map(s=>s.threadId);}
export function forgetSearchSessions(project:string,ids:string[]){for(const id of ids)if(!searchSession(project,id)?.active)sessions.delete(key(project,id));changed();}
export function dismissSearchError(project:string,threadId:string){const s=searchSession(project,threadId);if(s){s.error='';changed();}}
/** Lives outside the mounted page: navigating never cancels another conversation. */
export async function startSearchSession(project:string,threadId:string,text:string,base:ChatMessage[],modelLabel:string,selection:ModelSelection={profileId:'',model:''}){
 if(searchSession(project,threadId)?.active)return;
 const user:ChatMessage={role:'user',text,created:Date.now()/1000};
 const assistant:ChatMessage={role:'assistant',text:'',reasoning:'',modelLabel,created:Date.now()/1000};
 const session:Session={project,threadId,streamId:crypto.randomUUID(),active:true,sequence:0,messages:[...base,user,assistant],error:''};
 sessions.set(key(project,threadId),session);beginSearchTrace(session.streamId);changed();
 // Coalesce bursts without making every token synchronously rerender the whole page.
 let timer:ReturnType<typeof setTimeout>|undefined;let latest:ChatMessage|undefined;let sequence=0;
 const publish=()=>{timer=undefined;if(latest){session.messages=[...base,user,latest];session.sequence=sequence;latest=undefined;changed();}};
 try{session.messages=await streamChat({...selection,project,chatId:threadId,message:text,streamId:session.streamId},event=>{if(event.type==='update'){
  sequence=receiveSearchTrace(session.streamId,event.emittedAt);latest={...assistant,text:event.text||'',reasoning:event.reasoning||''};
  if(timer===undefined)timer=setTimeout(publish,50);
 }});}

 catch(e){if(timer!==undefined)clearTimeout(timer);publish();session.error=message(e);try{const saved=await rpc<ChatThread>('chat.get',{project,id:threadId});session.messages=saved.messages||session.messages;}catch{/* Keep the received tokens if reload fails. */}}
 finally{if(timer!==undefined)clearTimeout(timer);latest=undefined;session.sequence=sequence;session.active=false;endSearchTrace(session.streamId,!!session.error);changed();}
}
export async function stopSearchSession(project:string,threadId:string){const s=searchSession(project,threadId);if(s?.active)await rpc('chat.cancel',{streamId:s.streamId});}
