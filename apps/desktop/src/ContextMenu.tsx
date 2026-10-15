import {useEffect,useLayoutEffect,useRef,type ReactNode} from 'react';
import {createPortal} from 'react-dom';

export type ContextMenuAnchor={trigger:HTMLElement;x:number;y:number};
/** Context actions share the overflow menu's appearance and keyboard contract. */
export default function ContextMenu({anchor,label,children,onClose}:{anchor:ContextMenuAnchor;label:string;children:ReactNode;onClose:()=>void}){
 const panel=useRef<HTMLDivElement>(null);
 const close=useRef(onClose);close.current=onClose;
 useLayoutEffect(()=>{
  const menu=panel.current;if(!menu)return;
  const position=()=>{const rect=menu.getBoundingClientRect();Object.assign(menu.style,{left:`${Math.max(12,Math.min(anchor.x,innerWidth-rect.width-12))}px`,top:`${Math.max(12,Math.min(anchor.y,innerHeight-rect.height-12))}px`,visibility:'visible'});};
  menu.querySelectorAll('button').forEach(b=>{b.setAttribute('role','menuitem');b.tabIndex=-1;});
  position();menu.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
  const observer=new ResizeObserver(position);observer.observe(menu);return()=>observer.disconnect();
 },[anchor]);
 useEffect(()=>{
  const dismiss=(e:Event)=>{if(!panel.current?.contains(e.target as Node)&&!anchor.trigger.contains(e.target as Node))close.current();};
  const viewport=()=>close.current();
  document.addEventListener('pointerdown',dismiss);document.addEventListener('focusin',dismiss);
  window.addEventListener('resize',viewport);window.addEventListener('scroll',viewport,true);
  return()=>{document.removeEventListener('pointerdown',dismiss);document.removeEventListener('focusin',dismiss);window.removeEventListener('resize',viewport);window.removeEventListener('scroll',viewport,true);};
 },[anchor]);
 function restore(){anchor.trigger.focus();onClose();}
 return createPortal(<div ref={panel} role="menu" aria-label={label} className="stage-action-popover" style={{visibility:'hidden'}}
  onClickCapture={e=>{const button=(e.target as Element).closest('button');if(button&&!button.disabled)anchor.trigger.focus();}}
  onClick={e=>{const button=(e.target as Element).closest('button');if(button&&!button.disabled)onClose();}}
  onKeyDown={e=>{
   if(e.key==='Escape'){e.preventDefault();e.stopPropagation();restore();return;}
   if(e.key==='Tab'){restore();return;}
   if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;e.preventDefault();
   const buttons=Array.from(panel.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')||[]);if(!buttons.length)return;
   const index=buttons.indexOf(document.activeElement as HTMLButtonElement);
   buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();
  }}>{children}</div>,document.body);
}
