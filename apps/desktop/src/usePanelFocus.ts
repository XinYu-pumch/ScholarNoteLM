import {useEffect,useRef,type RefObject} from 'react';
/** A non-modal inspector returns focus to its opening control when dismissed. */
export function usePanelFocus(open:boolean,panel:RefObject<HTMLElement|null>){
 const previous=useRef<HTMLElement|null>(null);
 useEffect(()=>{if(!open||!panel.current)return;
  const active=document.activeElement as HTMLElement;
  if(!panel.current.contains(active))previous.current=active;
  panel.current.querySelector<HTMLElement>('button:not(:disabled),input:not(:disabled)')?.focus({preventScroll:true});
  return()=>{requestAnimationFrame(()=>{const active=document.activeElement;if(previous.current?.isConnected&&(!active||active===document.body||panel.current?.contains(active)))previous.current.focus({preventScroll:true});});};
 },[open]);
}
