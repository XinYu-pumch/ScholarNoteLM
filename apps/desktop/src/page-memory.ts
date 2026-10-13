import {useCallback,useLayoutEffect,useState,type RefObject,type Dispatch,type SetStateAction} from 'react';
const memory=new Map<string,unknown>();
export const pageMemory=<T,>(key:string)=>memory.get(key) as T|undefined;
export function rememberPage(key:string,value:unknown){memory.delete(key);memory.set(key,value);while(memory.size>100)memory.delete(memory.keys().next().value!);}
export function forgetPage(project:string){for(const key of memory.keys())if(key.startsWith(project+':'))memory.delete(key);}
export function usePageState<T>(key:string,initial:T|(()=>T)):[T,Dispatch<SetStateAction<T>>]{
 const read=()=>memory.has(key)?memory.get(key) as T:typeof initial==='function'?(initial as ()=>T)():initial;
 const [cell,setCell]=useState(()=>({key,value:read()}));
 // Some workspaces stay mounted while their identity changes. Never reuse the previous key's value.
 const current=cell.key===key?cell:{key,value:read()};
 if(cell.key!==key)setCell(current);
 const set=useCallback<Dispatch<SetStateAction<T>>>(next=>setCell(previous=>{
  const value=typeof next==='function'?(next as (p:T)=>T)(previous.key===key?previous.value:read()):next;
  rememberPage(key,value);return {key,value};
 }),[key]);
 return [current.value,set];
}
export function useScrollMemory(key:string,ref:RefObject<HTMLElement|null>,ready=true){
 useLayoutEffect(()=>{if(!ready)return;const node=ref.current;if(!node)return;const saved=pageMemory<number>(key);let pending=saved!==undefined;
  const restore=()=>{if(!pending||saved===undefined)return;node.scrollTop=saved;if(node.scrollTop>=saved-1)pending=false;};
  // Async content can initially be shorter than the saved offset. Restore when it has grown.
  const observer=new ResizeObserver(restore);observer.observe(node);
  const children=new MutationObserver(()=>{for(const child of node.children)observer.observe(child);restore();});
  children.observe(node,{childList:true,subtree:true});for(const child of node.children)observer.observe(child);restore();
  const user=()=>{pending=false;};node.addEventListener('wheel',user,{passive:true});node.addEventListener('touchstart',user,{passive:true});node.addEventListener('pointerdown',user);node.addEventListener('keydown',user);
  return()=>{rememberPage(key,pending?saved:node.scrollTop);observer.disconnect();children.disconnect();node.removeEventListener('wheel',user);node.removeEventListener('touchstart',user);node.removeEventListener('pointerdown',user);node.removeEventListener('keydown',user);};
 },[key,ready]);
}
