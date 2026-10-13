import {t as tr} from './i18n';
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {CheckSquare,Copy,GitBranch,LoaderCircle,MessageSquare,MoreHorizontal,Pencil,Trash2} from 'lucide-react';
import ConversationDialog from './ConversationDialog';
import {message} from './research-api';
import './conversations.css';
type Item={id:string;name:string;parentId?:string|null};
type Props={items:Item[];currentId?:string;className:string;label:string;disabled?:boolean;mutationDisabled?:boolean;runningIds?:string[];onChoose:(id:string)=>void;onRename:(id:string,name:string)=>Promise<void>;onCopy:(id:string)=>Promise<void>;onDelete:(ids:string[])=>Promise<void>};
export default function ConversationList({items,currentId,className,label,disabled=false,mutationDisabled=false,runningIds=[],onChoose,onRename,onCopy,onDelete}:Props){
 const [selecting,setSelecting]=useState(false),[selected,setSelected]=useState<string[]>([]);
 const [menu,setMenu]=useState<{item:Item;x:number;y:number;trigger:HTMLElement}|null>(null);
 const [dialog,setDialog]=useState<{mode:'rename'|'delete';items:Item[]}|null>(null);
 const [pending,setPending]=useState(false),[error,setError]=useState('');
 const menuRef=useRef<HTMLDivElement>(null),allRef=useRef<HTMLInputElement>(null);
 const locked=disabled||pending,ids=selected.filter(id=>items.some(t=>t.id===id));
 const all=items.length>0&&ids.length===items.length;
 useEffect(()=>{if(allRef.current)allRef.current.indeterminate=ids.length>0&&!all;},[ids.length,all]);
 useEffect(()=>{if(disabled)setMenu(null);},[disabled]);
 useLayoutEffect(()=>{if(!menu||!menuRef.current)return;const el=menuRef.current,r=el.getBoundingClientRect();el.style.left=`${Math.max(8,Math.min(menu.x,window.innerWidth-r.width-8))}px`;el.style.top=`${Math.max(8,Math.min(menu.y,window.innerHeight-r.height-8))}px`;el.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();},[menu]);
 useEffect(()=>{if(!menu)return;const close=(e:Event)=>{if(e.type==='pointerdown'&&menuRef.current?.contains(e.target as Node))return;setMenu(null);};window.addEventListener('pointerdown',close);window.addEventListener('resize',close);window.addEventListener('scroll',close,true);return()=>{window.removeEventListener('pointerdown',close);window.removeEventListener('resize',close);window.removeEventListener('scroll',close,true);};},[menu]);
 function toggle(id:string){setSelected(prev=>prev.includes(id)?prev.filter(v=>v!==id):[...prev,id]);}
 function open(item:Item,trigger:HTMLElement,x?:number,y?:number){if(locked||selecting)return;const r=trigger.getBoundingClientRect();setError('');setMenu({item,trigger,x:x??r.left,y:y??r.bottom});}
 function closeMenu(){menu?.trigger.focus();setMenu(null);}
 async function duplicate(id:string){closeMenu();setPending(true);setError('');try{await onCopy(id);}catch(e){setError(message(e));}finally{setPending(false);}}
 return <div className="conversation-manager">
  <div className="conversation-selection">
   {!selecting?<button disabled={locked||!items.length} onClick={()=>{setSelecting(true);setSelected([]);setMenu(null);}}><CheckSquare size={13}/>{tr("选择对话")}</button>:<>
    <label><input ref={allRef} type="checkbox" aria-label={tr("全选{p0}",{p0:label})} checked={all} disabled={locked} onChange={()=>setSelected(all?[]:items.map(t=>t.id))}/>{tr("全选")}</label>
    <span>{tr("已选")}{ids.length}</span><button disabled={locked} onClick={()=>{setSelecting(false);setSelected([]);}}>{tr("取消")}</button>
    <button className="conversation-delete-selected" disabled={locked||mutationDisabled||ids.some(id=>runningIds.includes(id))||!ids.length} onClick={()=>setDialog({mode:'delete',items:items.filter(t=>ids.includes(t.id))})}><Trash2 size={13}/>{tr("删除所选（")}{ids.length}）</button>
   </>}
  </div>
  {error&&<p className="conversation-error" role="alert">{tr(error)}</p>}
  <nav className={`${className} conversation-items`} aria-label={tr(label)}>
   {items.map(t=><div key={t.id} className={`conversation-row${currentId===t.id?' selected':''}${ids.includes(t.id)&&selecting?' is-checked':''}`} onContextMenu={e=>{e.preventDefault();open(t,e.currentTarget.querySelector('button')!,e.clientX,e.clientY);}}>
    {selecting&&<input type="checkbox" aria-label={tr("选择对话：{p0}",{p0:t.name})} checked={ids.includes(t.id)} disabled={locked} onChange={()=>toggle(t.id)}/>}
    <button className="conversation-open" disabled={locked} title={t.name} aria-current={currentId===t.id?'page':undefined} onClick={()=>selecting?toggle(t.id):onChoose(t.id)} onKeyDown={e=>{if(e.key==='ContextMenu'||e.shiftKey&&e.key==='F10'){e.preventDefault();open(t,e.currentTarget);}}}>
     {t.parentId?<GitBranch size={14}/>:<MessageSquare size={14}/>}<span>{t.name}</span>{runningIds.includes(t.id)&&<LoaderCircle size={12} className="spin"/>}
    </button>
    {!selecting&&<button className="conversation-more" aria-label={tr("管理对话：{p0}",{p0:t.name})} title={tr("管理对话")} aria-haspopup="menu" aria-expanded={menu?.item.id===t.id} disabled={locked} onClick={e=>open(t,e.currentTarget)}><MoreHorizontal size={14}/></button>}
   </div>)}
   {!items.length&&<p>{tr("暂无对话")}</p>}
  </nav>
  {menu&&createPortal(<div ref={menuRef} className="conversation-menu" role="menu" aria-label={tr("管理对话：{p0}",{p0:menu.item.name})} style={{left:menu.x,top:menu.y}} onKeyDown={e=>{
   if(e.key==='Escape'||e.key==='Tab'){if(e.key==='Escape')e.preventDefault();closeMenu();}
   if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const buttons=Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));const i=buttons.indexOf(document.activeElement as HTMLButtonElement);const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;buttons[next]?.focus();}
  }}>
   <button role="menuitem" onClick={()=>{setDialog({mode:'rename',items:[menu.item]});closeMenu();}}><Pencil size={14}/>{tr("重命名")}</button>
   <button role="menuitem" disabled={mutationDisabled||runningIds.includes(menu.item.id)} onClick={()=>void duplicate(menu.item.id)}><Copy size={14}/>{tr("复制对话")}</button>
   <button role="menuitem" disabled={mutationDisabled||runningIds.includes(menu.item.id)} onClick={()=>{setDialog({mode:'delete',items:[menu.item]});closeMenu();}}><Trash2 size={14}/>{tr("删除")}</button>
  </div>,document.body)}
  {dialog&&<ConversationDialog mode={dialog.mode} name={dialog.items[0].name} count={dialog.items.length} onClose={()=>setDialog(null)} onSubmit={async name=>{setPending(true);try{if(dialog.mode==='rename')await onRename(dialog.items[0].id,name);else{await onDelete(dialog.items.map(t=>t.id));setSelected([]);setSelecting(false);}}finally{setPending(false);}}}/>}
 </div>;
}
