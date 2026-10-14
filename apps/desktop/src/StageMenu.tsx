import {t as tr} from './i18n';
import {useEffect,useId,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {ChevronDown,MoreHorizontal} from 'lucide-react';

/** A body-level menu: page grids and native popover sizing cannot stretch its rows. */
export default function StageMenu({children,label='更多操作',icon=false,caption}:{children:ReactNode;label?:string;icon?:boolean;caption?:string}){
 const id=useId(),trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null);
 const [open,setOpen]=useState(false);
 const keyboardOpen=useRef<false|'first'|'last'>(false);
 function close(focus=false){setOpen(false);if(focus)trigger.current?.focus();}
 useLayoutEffect(()=>{
  if(!open)return;
  const menu=panel.current,button=trigger.current;if(!menu||!button)return;
  const position=()=>{
   const rect=button.getBoundingClientRect();
   const height=menu.getBoundingClientRect().height,width=menu.getBoundingClientRect().width;
   const top=rect.bottom+6+height<=innerHeight-12?rect.bottom+6:Math.max(12,rect.top-height-6);
   Object.assign(menu.style,{left:`${Math.max(12,Math.min(rect.right-width,innerWidth-width-12))}px`,top:`${top}px`,visibility:'visible'});
  };
  menu.querySelectorAll('button').forEach(b=>{b.setAttribute('role','menuitem');b.tabIndex=-1;});
  position();if(keyboardOpen.current){const buttons=menu.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');buttons[keyboardOpen.current==='last'?buttons.length-1:0]?.focus();}
  const observer=new ResizeObserver(position);observer.observe(menu);
  window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
  return()=>{observer.disconnect();window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true);};
 },[open]);
 useEffect(()=>{
  if(!open)return;
  const outside=(e:PointerEvent)=>{if(!panel.current?.contains(e.target as Node)&&!trigger.current?.contains(e.target as Node))close();};
  const focus=(e:FocusEvent)=>{if(!panel.current?.contains(e.target as Node)&&!trigger.current?.contains(e.target as Node))close();};
  const escape=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!e.defaultPrevented&&!document.querySelector('dialog[open]:last-of-type')?.contains(document.activeElement)){e.preventDefault();close(true);}};
  const other=(e:Event)=>{if((e as CustomEvent).detail!==id)close();};
  document.addEventListener('keydown',escape);document.addEventListener('pointerdown',outside);document.addEventListener('focusin',focus);window.addEventListener('stage-menu-open',other);
  return()=>{document.removeEventListener('keydown',escape);document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',focus);window.removeEventListener('stage-menu-open',other);};
 },[open,id]);
 function show(keyboard:false|'first'|'last'){keyboardOpen.current=keyboard;window.dispatchEvent(new CustomEvent('stage-menu-open',{detail:id}));setOpen(true);if(keyboard)panel.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();}
 return <><button ref={trigger} type="button" className={icon?'icon-button action-menu-trigger':'stage-menu-trigger'} title={tr(label)} aria-label={tr(label)} aria-haspopup="menu" aria-expanded={open} aria-controls={open?id:undefined}
  onClick={e=>open?close():show(e.detail===0?'first':false)} onKeyDown={e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();show(e.key==='ArrowUp'?'last':'first');}if(e.key==='Escape')close(true);}}>{icon?<MoreHorizontal size={18}/>:<>{tr(caption||"更多")}<ChevronDown size={12}/></>}</button>
  {open&&createPortal(<div ref={panel} id={id} role="menu" aria-label={tr(label)} className="stage-action-popover" style={{visibility:'hidden'}}
   onClickCapture={e=>{const b=(e.target as Element).closest('button');if(b&&!b.disabled)trigger.current?.focus();}} onClick={e=>{const b=(e.target as Element).closest('button');if(b&&!b.disabled)close();}}
   onKeyDown={e=>{
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);return;}
    if(e.key==='Tab'){close(true);return;}
    if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;e.preventDefault();
    const buttons=Array.from(panel.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')||[]);if(!buttons.length)return;
    const index=buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();
   }}>{children}</div>,trigger.current?.closest('dialog')||document.body)}
 </>;
}
