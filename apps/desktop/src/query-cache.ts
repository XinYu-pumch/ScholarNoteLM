/** Bounded, in-memory read cache. Never store credentials or mutation results. */
type Snapshot<T=unknown>={data:T|undefined;error:string;updated:number};
type Listener=()=>void;
type Entry={snapshot:Snapshot;generation:number;promise?:Promise<unknown>;listeners:Set<Listener>;refresh?:()=>void;bytes:number};
const entries=new Map<string,Entry>();
const MAX_BYTES=32*1024*1024,MAX_ENTRIES=80;
export const queryKey=(action:string,args:Record<string,unknown>={})=>JSON.stringify([action,Object.fromEntries(Object.entries(args).sort(([a],[b])=>a.localeCompare(b)))]);
function entry(key:string){let e=entries.get(key);if(!e){e={snapshot:{data:undefined,error:'',updated:0},generation:0,listeners:new Set(),bytes:0};entries.set(key,e);}return e;}
function trim(){let bytes=[...entries.values()].reduce((n,e)=>n+e.bytes,0);for(const [key,e] of entries){if(bytes<=MAX_BYTES&&entries.size<=MAX_ENTRIES)break;if(!e.listeners.size&&!e.promise){entries.delete(key);bytes-=e.bytes;}}}
export function snapshot<T>(key:string){return entry(key).snapshot as Snapshot<T>;}
export function peek<T>(action:string,args:Record<string,unknown>={}){return snapshot<T>(queryKey(action,args)).data;}
export function subscribe(key:string,listener:Listener){const e=entry(key);e.listeners.add(listener);return()=>{e.listeners.delete(listener);trim();};}
export function setRefresh(key:string,refresh:()=>void){entry(key).refresh=refresh;}
export async function read<T>(key:string,load:()=>Promise<T>,maxAge=0):Promise<T>{
 const e=entry(key);if(maxAge&&e.snapshot.data!==undefined&&Date.now()-e.snapshot.updated<maxAge)return e.snapshot.data as T;
 if(e.promise)return e.promise as Promise<T>;
 const generation=e.generation;
 const promise=load().then(value=>{
  if(e.generation!==generation)return read(key,load);
  const encoded=JSON.stringify(value),same=e.snapshot.data!==undefined&&encoded===JSON.stringify(e.snapshot.data);
  e.bytes=encoded.length*2;e.snapshot={data:same?e.snapshot.data:value,error:'',updated:Date.now()};
  e.listeners.forEach(fn=>fn());return e.snapshot.data as T;
 }).catch(error=>{if(e.generation!==generation)return read(key,load);if(e.generation===generation){e.snapshot={...e.snapshot,error:String(error)};e.listeners.forEach(fn=>fn());}throw error;}).finally(()=>{if(e.promise===promise)e.promise=undefined;trim();});
 e.promise=promise;return promise as Promise<T>;
}
export function invalidate(project?:string,actions?:string[],clear=false){
 for(const [key,e] of entries){const [action,args]=JSON.parse(key);if(actions&&!actions.includes(action))continue;if(project&&args.project&&args.project!==project)continue;
  e.generation++;e.promise=undefined;e.snapshot={data:clear?undefined:e.snapshot.data,error:'',updated:0};if(clear)e.bytes=0;
  e.listeners.forEach(fn=>fn());if(e.listeners.size)e.refresh?.();
 }
}

type Poll={users:Map<symbol,{interval:(data:unknown)=>number;load:()=>Promise<unknown>}>;timer?:ReturnType<typeof setTimeout>;running:boolean};
const polls=new Map<string,Poll>();
/** A single poll per resource, regardless of the number of mounted consumers. */
export function polling(key:string,load:()=>Promise<unknown>,interval:(data:unknown)=>number){
 let p=polls.get(key);if(!p){p={users:new Map(),running:false};polls.set(key,p);}const poll=p,token=Symbol();poll.users.set(token,{interval,load});
 const schedule=()=>{if(poll.timer)clearTimeout(poll.timer);if(!poll.users.size||poll.running)return;const delay=Math.min(...[...poll.users.values()].map(u=>u.interval(snapshot(key).data)).filter(v=>v>0));if(!Number.isFinite(delay))return;poll.timer=setTimeout(async()=>{poll.running=true;try{await poll.users.values().next().value?.load();}catch{/* error is held by the resource */}finally{poll.running=false;schedule();}},delay);};
 schedule();return()=>{poll.users.delete(token);if(!poll.users.size){if(poll.timer)clearTimeout(poll.timer);polls.delete(key);}else schedule();};
}
