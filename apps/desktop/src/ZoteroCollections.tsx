import {useEffect,useRef} from 'react';
import {ChevronRight,Folder,FolderOpen,Search,X} from 'lucide-react';
export type Collection={key:string;name:string;path:string;parentCollection?:string|false};
export function ancestors(c:Collection,all:Collection[],byKey=new Map(all.map(v=>[v.key,v]))):string[]{
 const seen=new Set([c.key]),result:string[]=[];let parent=c.parentCollection;
 while(parent&&byKey.has(parent)&&!seen.has(parent)){result.push(parent);seen.add(parent);parent=byKey.get(parent)!.parentCollection;}return result;
}
export function canonicalSelection(keys:string[],all:Collection[]):string[]{
 const selected=new Set(keys);return all.filter(c=>selected.has(c.key)&&!ancestors(c,all).some(k=>selected.has(k))).map(c=>c.key);
}
function Check({mixed,...props}:{mixed:boolean}&React.InputHTMLAttributes<HTMLInputElement>){
 const ref=useRef<HTMLInputElement>(null);useEffect(()=>{if(ref.current)ref.current.indeterminate=mixed;},[mixed]);return <input {...props} ref={ref} type="checkbox"/>;
}
export default function ZoteroCollections({collections,selected,expanded,search,disabled,onSearch,onSelect,onExpand}:{collections:Collection[];selected:string[];expanded:string[];search:string;disabled:boolean;onSearch:(v:string)=>void;onSelect:(v:string[])=>void;onExpand:(v:string[])=>void}){
 const chosen=new Set(selected),open=new Set(expanded),query=search.trim().toLocaleLowerCase();
 const byKey=new Map(collections.map(c=>[c.key,c])),parents=new Map(collections.map(c=>[c.key,ancestors(c,collections,byKey)]));
 const matches=new Set(collections.filter(c=>c.name.toLocaleLowerCase().includes(query)).map(c=>c.key));
 const visible=new Set([...matches,...collections.filter(c=>matches.has(c.key)).flatMap(c=>parents.get(c.key)!)]);
 const tree=useRef<HTMLDivElement>(null),restored=useRef(false);
 useEffect(()=>{if(!collections.length||restored.current)return;restored.current=true;tree.current?.querySelector('[data-selected="true"]')?.scrollIntoView({block:'nearest'});},[collections]);
 function toggle(c:Collection){onSelect(canonicalSelection(chosen.has(c.key)?selected.filter(k=>k!==c.key):[...selected,c.key],collections));}
 function expand(c:Collection){onExpand(open.has(c.key)?expanded.filter(k=>k!==c.key):[...expanded,c.key]);}
 function nodes(parent:string|false,depth:number):React.ReactNode{
  return collections.filter(c=>(c.parentCollection||false)===parent&&(!query||visible.has(c.key))).map(c=>{
   const children=collections.some(v=>v.parentCollection===c.key),isOpen=!!query||open.has(c.key),inherited=parents.get(c.key)!.some(k=>chosen.has(k));
   const checked=chosen.has(c.key)||inherited,mixed=!checked&&collections.some(v=>chosen.has(v.key)&&parents.get(v.key)!.includes(c.key));
   return <li key={c.key} role="treeitem" aria-label={c.name} aria-expanded={children?isOpen:undefined} aria-checked={mixed?'mixed':checked}>
    <div className={`zotero-tree-row ${checked?'included':''} ${inherited?'inherited':''}`} data-selected={chosen.has(c.key)} style={{paddingLeft:8+depth*20}} title={c.path}>
     {children?<button type="button" className="zotero-tree-chevron" aria-label={`${isOpen?'折叠':'展开'} ${c.path}`} disabled={disabled||!!query} onClick={()=>expand(c)}><ChevronRight size={15} style={{transform:isOpen?'rotate(90deg)':undefined}}/></button>:<span className="zotero-tree-chevron"/>}
     <label><Check aria-label={`选择 ${c.path}`} checked={checked} mixed={mixed} disabled={disabled||inherited} onChange={()=>toggle(c)}/>{children&&isOpen?<FolderOpen size={17}/>:<Folder size={17}/>}<span>{c.name}</span></label>{inherited&&<small>已包含</small>}
    </div>{children&&isOpen&&<ul role="group">{nodes(c.key,depth+1)}</ul>}
   </li>;
  });
 }
 return <section className="zotero-tree-pane"><label className="zotero-tree-search"><Search size={16}/><input aria-label="搜索 Zotero 文件夹" placeholder="搜索文件夹…" value={search} disabled={disabled} onChange={e=>onSearch(e.target.value)}/>{search&&<button aria-label="清除文件夹搜索" disabled={disabled} onClick={()=>onSearch('')}><X size={14}/></button>}</label><div className="zotero-tree-tools"><span>我的文献库</span><button disabled={disabled||!!query} onClick={()=>onExpand([])}>全部折叠</button></div><div className="zotero-tree-scroll" ref={tree}><ul role="tree" aria-label="Zotero 文件夹" aria-multiselectable="true" onKeyDown={e=>{
 if(e.key!=='ArrowDown'&&e.key!=='ArrowUp')return;const controls=Array.from(e.currentTarget.querySelectorAll<HTMLInputElement>('input:not(:disabled)'));const index=controls.indexOf(e.target as HTMLInputElement);if(index<0)return;e.preventDefault();controls[Math.max(0,Math.min(controls.length-1,index+(e.key==='ArrowDown'?1:-1)))]?.focus();
 }}>{nodes(false,0)}</ul>{query&&!matches.size&&<p className="zotero-tree-empty">没有匹配的文件夹</p>}{!collections.length&&<p className="zotero-tree-empty">{disabled?'正在连接 Zotero…':'个人文献库中没有文件夹'}</p>}</div><p className="zotero-tree-help">勾选父文件夹将自动包含全部子文件夹。</p></section>;
}
