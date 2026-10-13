import {isComposing} from './keyboard';
import {useEffect, useId, useRef, useState, type KeyboardEvent} from 'react';

/** Manual activation: arrows move focus; Enter/Space activate the focused tab. */
export function useTabs(value: string, items: readonly string[], select: (value: string) => void) {
  const id=useId();
  const [focused,setFocused]=useState(value);
  const buttons=useRef(new Map<string,HTMLButtonElement>());
  useEffect(()=>setFocused(value),[value]);
  const tabId=(item:string)=>`${id}-tab-${item}`;
  const panelId=(item:string)=>`${id}-panel-${item}`;
  function key(event:KeyboardEvent<HTMLButtonElement>,item:string){
    if(isComposing(event)||event.altKey||event.ctrlKey||event.metaKey)return;
    const index=items.indexOf(item);
    const next=event.key==='Home'?0:event.key==='End'?items.length-1:event.key==='ArrowRight'?(index+1)%items.length:event.key==='ArrowLeft'?(index-1+items.length)%items.length:-1;
    if(next<0)return;
    event.preventDefault();setFocused(items[next]);buttons.current.get(items[next])?.focus();
  }
  return {
    tab: (item:string)=>({role:'tab' as const,id:tabId(item),'aria-selected':item===value,'aria-controls':panelId(item),tabIndex:item===focused?0:-1,
      ref:(element:HTMLButtonElement|null)=>{if(element)buttons.current.set(item,element);else buttons.current.delete(item);},
      onFocus:()=>setFocused(item),onKeyDown:(event:KeyboardEvent<HTMLButtonElement>)=>key(event,item),onClick:(event:React.MouseEvent<HTMLButtonElement>)=>{event.currentTarget.focus();if(item!==value)select(item);}}),
    panel:(item:string)=>({role:'tabpanel' as const,id:panelId(item),'aria-labelledby':tabId(item),tabIndex:0}),
  };
}
