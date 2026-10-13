import {t as tr} from './i18n';
import {isComposing} from './keyboard';
import {Children,isValidElement,useEffect,useId,useLayoutEffect,useRef,useState,type ReactNode,type SelectHTMLAttributes,type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';
import {Check,ChevronDown} from 'lucide-react';
type Option={value:string;label:string;disabled:boolean};
type Props=Omit<SelectHTMLAttributes<HTMLSelectElement>,'onChange'|'multiple'|'size'> & {onChange?:(event:{target:{value:string}})=>void};
function text(node:ReactNode):string{return Children.toArray(node).map(n=>isValidElement<{children?:ReactNode}>(n)?text(n.props.children):String(n)).join('');}
function optionsIn(nodes:ReactNode):Option[]{return Children.toArray(nodes).flatMap(n=>{
 if(!isValidElement<{value?:string;disabled?:boolean;children?:ReactNode}>(n))return [];
 if(n.type==='option')return [{value:String(n.props.value??text(n.props.children)),label:text(n.props.children),disabled:!!n.props.disabled}];
 return optionsIn(n.props.children);
});}
/** App-owned popup: identical colors in WKWebView, Chromium and Windows WebView. */
export default function Select({children,value,defaultValue,onChange,disabled,id,className,name,required,...rest}:Props){
 const autoId=useId();const uid=id||autoId;const trigger=useRef<HTMLButtonElement>(null);const menu=useRef<HTMLDivElement>(null);
 const [local,setLocal]=useState(String(defaultValue??''));const selected=String(value??local);const options=optionsIn(children);
 const [open,setOpen]=useState(false);const [active,setActive]=useState(0);const [position,setPosition]=useState({left:0,top:0,width:0,maxHeight:280});const [container,setContainer]=useState<Element|null>(null);const typing=useRef({text:'',time:0});
 const chosen=options.find(o=>o.value===selected);
 function close(focus=false){setOpen(false);if(focus)trigger.current?.focus();}
 function show(){if(disabled)return;trigger.current?.focus();setContainer(trigger.current?.closest('dialog')||document.body);setActive(Math.max(0,options.findIndex(o=>o.value===selected&&!o.disabled)));setOpen(true);}
 function pick(index:number){const opt=options[index];if(!opt||opt.disabled)return;setLocal(opt.value);onChange?.({target:{value:opt.value}});close(true);}
 function key(e:KeyboardEvent){
  if(isComposing(e))return;
  if(e.key==='Escape'&&open){e.preventDefault();e.stopPropagation();close(true);return;}
  if(e.key==='Tab'){close();return;}
  if(['Enter',' ','ArrowDown','ArrowUp','Home','End'].includes(e.key)){
   e.preventDefault();e.stopPropagation();if(!open){show();return;}if(e.key==='Enter'||e.key===' '){pick(active);return;}
   let next=e.key==='Home'?0:e.key==='End'?options.length-1:active+(e.key==='ArrowUp'?-1:1);const direction=e.key==='ArrowUp'||e.key==='End'?-1:1;
   for(let i=0;i<options.length;i++){next=(next+options.length)%options.length;if(!options[next]?.disabled)break;next+=direction;}setActive(next);
  }else if(e.key.length===1&&!e.metaKey&&!e.ctrlKey&&!e.altKey){
   if(!open)show();const now=Date.now();typing.current={text:(now-typing.current.time<700?typing.current.text:'')+e.key.toLowerCase(),time:now};const index=options.findIndex(o=>!o.disabled&&o.label.toLowerCase().startsWith(typing.current.text));if(index>=0)setActive(index);
  }
 }
 useLayoutEffect(()=>{if(!open)return;const place=()=>{const r=trigger.current?.getBoundingClientRect();if(!r)return;const height=Math.min(280,options.length*38+12);const below=innerHeight-r.bottom-12;const above=r.top-12;const up=below<height&&above>below;const maxHeight=Math.max(60,Math.min(280,up?above:below));const width=Math.min(Math.max(r.width,180),innerWidth-24);setPosition({left:Math.max(12,Math.min(r.left,innerWidth-width-12)),top:up?Math.max(12,r.top-Math.min(height,maxHeight)-6):r.bottom+6,width,maxHeight});};place();window.addEventListener('resize',place);const onScroll=(e:Event)=>{if(menu.current?.contains(e.target as Node))return;close();};document.addEventListener('scroll',onScroll,true);return()=>{window.removeEventListener('resize',place);document.removeEventListener('scroll',onScroll,true);};},[open,options.length]);
 useEffect(()=>{if(!open)return;const outside=(e:PointerEvent)=>{if(!trigger.current?.contains(e.target as Node)&&!menu.current?.contains(e.target as Node))close();};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[open]);
 useEffect(()=>{if(disabled)setOpen(false);},[disabled]);
 useEffect(()=>{const list=menu.current;const row=list?.children[active] as HTMLElement|undefined;if(!list||!row)return;if(row.offsetTop<list.scrollTop)list.scrollTop=row.offsetTop;else if(row.offsetTop+row.offsetHeight>list.scrollTop+list.clientHeight)list.scrollTop=row.offsetTop+row.offsetHeight-list.clientHeight;},[active,open]);
 return <span className={`app-select ${className||''}`}>
  {name&&<input type="hidden" name={name} value={selected}/>}
  <button ref={trigger} id={uid} type="button" role="combobox" aria-label={tr(rest['aria-label'])} aria-labelledby={rest['aria-labelledby']} aria-describedby={rest['aria-describedby']} aria-required={required} aria-invalid={rest['aria-invalid']} aria-haspopup="listbox" aria-expanded={open} aria-controls={open?`${uid}-list`:undefined} aria-activedescendant={open?`${uid}-option-${active}`:undefined} className="app-select-trigger" disabled={disabled} title={rest.title||chosen?.label} onClick={()=>open?close():show()} onKeyDown={key} onDoubleClick={e=>e.stopPropagation()} onBlur={e=>{if(!menu.current?.contains(e.relatedTarget as Node))close();}}><span>{chosen?.label||selected||tr("请选择")}</span><ChevronDown size={14}/></button>
  {open&&container&&createPortal(<div ref={menu} id={`${uid}-list`} role="listbox" aria-label={tr(rest['aria-label'])} className="app-select-menu" style={{position:'fixed',...position}} onPointerDown={e=>e.preventDefault()} onClick={e=>e.stopPropagation()}>{options.length?options.map((o,i)=><div key={`${o.value}-${i}`} id={`${uid}-option-${i}`} role="option" aria-selected={o.value===selected} aria-disabled={o.disabled} className={`app-select-option ${i===active?'active':''} ${o.value===selected?'selected':''}`} onPointerMove={()=>{if(!o.disabled)setActive(i);}} onClick={()=>pick(i)}><span>{o.label}</span>{o.value===selected&&<Check size={14}/>}</div>):<div className="app-select-empty">{tr("暂无可选项")}</div>}</div>,container)}
 </span>;
}
