import {useLayoutEffect,useState,type RefObject,type Dispatch,type SetStateAction} from 'react';
const memory=new Map<string,unknown>();
export const pageMemory=<T,>(key:string)=>memory.get(key) as T|undefined;
export function rememberPage(key:string,value:unknown){memory.delete(key);memory.set(key,value);while(memory.size>100)memory.delete(memory.keys().next().value!);}
export function forgetPage(project:string){for(const key of memory.keys())if(key.startsWith(project+':'))memory.delete(key);}
export function usePageState<T>(key:string,initial:T|(()=>T)):[T,Dispatch<SetStateAction<T>>]{
 const [value,setValue]=useState<T>(()=>memory.has(key)?memory.get(key) as T:typeof initial==='function'?(initial as ()=>T)():initial);
 const set:Dispatch<SetStateAction<T>>=next=>setValue(previous=>{const value=typeof next==='function'?(next as (p:T)=>T)(previous):next;rememberPage(key,value);return value;});
 return [value,set];
}
export function useScrollMemory(key:string,ref:RefObject<HTMLElement|null>){
 useLayoutEffect(()=>{const node=ref.current;if(!node)return;const saved=pageMemory<number>(key);if(saved!==undefined)node.scrollTop=saved;
  return()=>rememberPage(key,node.scrollTop);
 },[key]);
}
