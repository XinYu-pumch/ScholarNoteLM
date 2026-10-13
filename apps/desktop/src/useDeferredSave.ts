import {useEffect,useRef} from 'react';
import {registerNavigationGuard} from './navigation';
/** Serialize automatic writes; navigation/quit waits for the most recent value. */
export function useDeferredSave<T>(write:(value:T)=>Promise<unknown>,onError:(error:unknown)=>void,delay=400){
 const current=useRef({write,onError});current.current={write,onError};
 const pending=useRef<{value:T;revision:number}|null>(null),committed=useRef(0),revision=useRef(0),queue=useRef(Promise.resolve()),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
 const flush=()=>{
  clearTimeout(timer.current);
  const task=queue.current.catch(()=>{}).then(async()=>{while(pending.current&&pending.current.revision>committed.current){const snapshot=pending.current;await current.current.write(snapshot.value);committed.current=snapshot.revision;}});
  queue.current=task;return task;
 };
 useEffect(()=>{const remove=registerNavigationGuard(async()=>{try{await flush();return true;}catch(e){current.current.onError(e);return false;}},-1);return()=>{remove();clearTimeout(timer.current);};},[]);
 return {schedule:(value:T)=>{pending.current={value,revision:++revision.current};clearTimeout(timer.current);timer.current=setTimeout(()=>void flush().catch(e=>current.current.onError(e)),delay);},flush};
}
