import {useCallback,useEffect,useSyncExternalStore} from 'react';
import {rpc} from './research-api';
import {snapshot,subscribe,setRefresh,queryKey,polling} from './query-cache';

export function useQuery<T>(action:string,args:Record<string,unknown>={},interval=0,activeInterval=interval,isActive?:(data:T)=>boolean,enabled=true){
 const key=queryKey(action,args);
 const subscribeQuery=useCallback((fn:()=>void)=>enabled?subscribe(key,fn):()=>{},[key,enabled]);
 const getSnapshot=useCallback(()=>snapshot<T>(key),[key]);
 const value=useSyncExternalStore(subscribeQuery,getSnapshot);
 useEffect(()=>{
  if(!enabled)return;
  const parsed=JSON.parse(key)[1];const load=()=>rpc<T>(action,parsed);const refresh=()=>{void load().catch(()=>{});};
  setRefresh(key,refresh);refresh();
  const stop=polling(key,load,data=>data&&isActive?.(data as T)?activeInterval:interval);
  const focus=()=>{if(document.visibilityState!=='hidden')refresh();};
  window.addEventListener('focus',focus);document.addEventListener('visibilitychange',focus);
  return()=>{stop();window.removeEventListener('focus',focus);document.removeEventListener('visibilitychange',focus);};
 },[key,interval,activeInterval,enabled]);
 return value;
}
