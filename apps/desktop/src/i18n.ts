import {useSyncExternalStore} from 'react';
import english from './locales/en.json';
export type Language='zh'|'en';
let locale:Language='zh';
try{const saved=localStorage.getItem('scholarnotelm-ui-language');locale=saved==='en'||saved==='zh'?saved:navigator.language.toLowerCase().startsWith('zh')?'zh':'en';}catch{/* State loading remains authoritative. */}
const listeners=new Set<()=>void>();
const templates=Object.entries(english).filter(([key])=>/\{p\d+\}/.test(key)).map(([key,value])=>({value,names:[...key.matchAll(/\{(p\d+)\}/g)].map(m=>m[1]),pattern:new RegExp('^'+key.split(/(\{p\d+\})/).map(part=>/^\{p\d+\}$/.test(part)?'([\\s\\S]*?)':part.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('')+'$')}));
export const uiLanguage=()=>locale;
export function configureLocale(value:Language){try{localStorage.setItem('scholarnotelm-ui-language',value);}catch{/* UI state is also persisted by the app. */}document.documentElement.lang=value==='en'?'en':'zh-CN';document.title=value==='en'?'ScholarNoteLM · Research workspace':'ScholarNoteLM · 研究工作台';if(locale===value)return;locale=value;listeners.forEach(fn=>fn());}
export function useLocale(){return useSyncExternalStore(fn=>{listeners.add(fn);return()=>listeners.delete(fn);},()=>locale);}
/** Only application-owned copy is passed here; research content is never translated. */
export function t<T extends string|number|undefined|null>(key:T,values:Record<string,unknown>={}):T{
 if(typeof key!=='string')return key;
 let template=locale==='en'?(english as Record<string,string>)[key]??key:key;
 if(locale==='en'&&template===key&&!Object.keys(values).length){for(const item of templates){const match=item.pattern.exec(key);if(match){template=item.value;values=Object.fromEntries(item.names.map((name,i)=>[name,match[i+1]]));break;}}}
 return template.replace(/\{(\w+)\}/g,(match,name)=>name in values?String(values[name]):match) as T;
}
