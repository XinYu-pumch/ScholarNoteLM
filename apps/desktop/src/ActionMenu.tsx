import {useEffect,useRef,type ReactNode} from 'react';
import {MoreHorizontal} from 'lucide-react';

/** Native disclosure keeps ordinary buttons keyboard-accessible without a partial ARIA menu. */
export default function ActionMenu({label,children}:{label:string;children:ReactNode}){
 const ref=useRef<HTMLDetailsElement>(null);
 useEffect(()=>{
  const outside=(event:PointerEvent)=>{if(event.target instanceof Node&&!ref.current?.contains(event.target))ref.current?.removeAttribute('open');};
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&ref.current?.open){ref.current.open=false;ref.current.querySelector('summary')?.focus();event.preventDefault();}};
  document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
  return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};
 },[]);
 return <details ref={ref} className="action-menu"><summary className="icon-button" aria-label={label} title={label}><MoreHorizontal size={18}/></summary><div className="action-menu-panel" onClick={event=>{if(event.target instanceof Element&&event.target.closest('button:not(:disabled)')&&ref.current){ref.current.open=false;ref.current.querySelector('summary')?.focus();}}}>{children}</div></details>;
}
