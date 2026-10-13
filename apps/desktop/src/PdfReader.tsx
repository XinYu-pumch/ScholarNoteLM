import {t as tr} from './i18n';
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,Minus,Plus,Search} from 'lucide-react';
import {rpc,message} from './research-api';
import type {PDFDocumentProxy,RenderTask} from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';

export type ReadingPosition={page?:number;zoom?:string;scroll?:number;pageOffset?:number;scrollLeft?:number;pdfVersion?:string;thread?:string};
type PageSize={width:number;height:number};
type Anchor={page:number;fraction?:number;legacyOffset?:number;left?:number;horizontal?:number;viewportX?:number;viewportY?:number};
type ZoomPoint={x:number;y:number};
const clampZoom=(n:number)=>Math.min(8,Math.max(.1,n));
const validZoom=(z?:string)=>z==='fit'||!Number.isFinite(Number(z))||Number(z)<=0?'fit':String(clampZoom(Number(z)));
const ZOOM_IDLE_MS=180; // Coalesce input before doing expensive PDF.js raster work.

/** Only nearby pages own canvases; off-screen pages retain their exact geometry. */
function PdfPage({pdf,number,size,scale,renderScale,root}:{pdf:PDFDocumentProxy;number:number;size:PageSize;scale:number;renderScale:number;root:HTMLDivElement|null}){
 const host=useRef<HTMLDivElement>(null),[visible,setVisible]=useState(false),[error,setError]=useState('');
 const published=useRef<{layer:HTMLDivElement;canvas:HTMLCanvasElement;scale:number}|null>(null),displayScale=useRef(scale);displayScale.current=scale;
 function release(){const old=published.current;if(old){old.layer.remove();old.canvas.width=0;old.canvas.height=0;published.current=null;}}
 useEffect(()=>{if(!root||!host.current)return;const observer=new IntersectionObserver(entries=>setVisible(entries[0].isIntersecting),{root,rootMargin:'500px 0px'});observer.observe(host.current);return()=>observer.disconnect();},[root]);
 useEffect(()=>()=>release(),[pdf,number,visible]);
 // Keep the last complete bitmap and its text layer together throughout a gesture.
 useLayoutEffect(()=>{const old=published.current;if(old)old.layer.style.transform=`scale(${scale/old.scale})`;},[scale]);
 useEffect(()=>{
  const target=host.current;if(!visible||!target)return;
  let alive=true,render:RenderTask|undefined,textLayer:InstanceType<typeof import('pdfjs-dist/legacy/build/pdf.mjs')['TextLayer']>|undefined;
  // Stage a replacement off-screen; never clear a readable page while PDF.js works.
  const layer=document.createElement('div'),canvas=document.createElement('canvas'),text=document.createElement('div');
  layer.className='paper-pdf-raster';layer.style.visibility='hidden';layer.setAttribute('aria-hidden','true');
  canvas.setAttribute('aria-label',tr("论文 PDF 第 {p0} 页",{p0:number}));text.className='textLayer';layer.append(canvas,text);target.append(layer);setError('');
  void (async()=>{try{
   const page=await pdf.getPage(number);if(!alive)return;
   const viewport=page.getViewport({scale:renderScale});
   const ratio=Math.min(window.devicePixelRatio||1,2,Math.sqrt(8_000_000/(viewport.width*viewport.height)),8192/Math.max(viewport.width,viewport.height));
   canvas.width=Math.ceil(viewport.width*ratio);canvas.height=Math.ceil(viewport.height*ratio);canvas.style.width=`${viewport.width}px`;canvas.style.height=`${viewport.height}px`;
   layer.style.width=`${viewport.width}px`;layer.style.height=`${viewport.height}px`;
   text.style.setProperty('--scale-factor',String(renderScale));text.style.setProperty('--total-scale-factor',String(renderScale));
   render=page.render({canvas,viewport,transform:[ratio,0,0,ratio,0,0]});await render.promise;if(!alive)return;
   const {TextLayer}=await import('pdfjs-dist/legacy/build/pdf.mjs');if(!alive)return;
   textLayer=new TextLayer({textContentSource:page.streamTextContent(),container:text,viewport});await textLayer.render();if(!alive)return;
   layer.style.transform=`scale(${displayScale.current/renderScale})`;layer.style.visibility='';layer.removeAttribute('aria-hidden');
   release();published.current={layer,canvas,scale:renderScale};
  }catch(e){if(alive)setError(message(e));}})();
  return()=>{alive=false;render?.cancel();textLayer?.cancel();if(published.current?.layer!==layer){layer.remove();canvas.width=0;canvas.height=0;}};
 },[pdf,number,renderScale,visible]);
 return <div ref={host} className="paper-pdf-page" data-pdf-page={number} role="region" aria-label={tr("PDF 第 {p0} 页",{p0:number})} style={{width:size.width*scale,height:size.height*scale}}>{error&&<p className="wb-alert" role="alert">{tr("第")}{number} {tr("页：")}{tr(error)}</p>}</div>;
}

export default function PdfReader({project,pmid,version,size,position,onPosition}:{project:string;pmid:string;version:string;size:number;position:ReadingPosition;onPosition:(v:ReadingPosition)=>void}){
 const saved=position.pdfVersion===version?position:{};
 const [pdf,setPdf]=useState<PDFDocumentProxy|null>(null),[sizes,setSizes]=useState<PageSize[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(0);
 const [page,setPage]=useState(saved.page||1),[pageInput,setPageInput]=useState(String(saved.page||1)),[zoom,setZoom]=useState(()=>validZoom(saved.zoom)),[zoomInput,setZoomInput]=useState('');
 const [query,setQuery]=useState(''),[found,setFound]=useState<number[]>([]),[finding,setFinding]=useState(false),[searched,setSearched]=useState(false);
 const scroll=useRef<HTMLDivElement>(null),[width,setWidth]=useState(600),searchId=useRef(0),onSave=useRef(onPosition);onSave.current=onPosition;
 const pending=useRef<Anchor|null>({page:saved.page||1,fraction:saved.pageOffset,legacyOffset:saved.scroll||0,left:saved.scrollLeft||0});
 const pages=useRef<HTMLDivElement>(null),ready=useRef(false);
 const scale=zoom==='fit'?Math.max(.1,(width-32)/Math.max(...sizes.map(p=>p.width),1)):Number(zoom);
 const [renderScale,setRenderScale]=useState<number|null>(null);
 useEffect(()=>{if(!pdf)return;if(renderScale===null){setRenderScale(scale);return;}const timer=setTimeout(()=>setRenderScale(scale),ZOOM_IDLE_MS);return()=>clearTimeout(timer);},[scale,pdf]);
 const current=useRef({scale,zoom});current.current={scale,zoom};
 function capture(point?:ZoomPoint):Anchor{
  const el=scroll.current;if(!el||!pages.current)return {page:1,fraction:0};
  const bounds=el.getBoundingClientRect(),y=point?Math.max(0,Math.min(el.clientHeight,point.y-bounds.top)):16,x=point?Math.max(0,Math.min(el.clientWidth,point.x-bounds.left)):el.clientWidth/2,top=bounds.top+y;
  const nodes=Array.from(pages.current.children) as HTMLElement[];
  const node=nodes.find(n=>n.getBoundingClientRect().bottom>top)||nodes.at(-1);
  if(!node)return {page:1,fraction:0};const rect=node.getBoundingClientRect();
  return {page:Number(node.dataset.pdfPage),fraction:(top-rect.top)/rect.height,left:el.scrollLeft,horizontal:(bounds.left+x-rect.left)/rect.width,viewportX:x,viewportY:y};
 }
 function save(){if(!ready.current||!scroll.current)return;const a=capture();setPage(a.page);setPageInput(String(a.page));onSave.current({page:a.page,pageOffset:a.fraction,scroll:scroll.current.scrollTop,scrollLeft:scroll.current.scrollLeft,zoom:current.current.zoom,pdfVersion:version});}
 function changeZoom(value:string,point?:ZoomPoint,anchor?:Anchor){const next=validZoom(value);if(next===current.current.zoom){setZoomInput(String(Math.round(current.current.scale*100)));return;}pending.current=anchor??capture(point);setZoom(next);}
 const changeRef=useRef(changeZoom);changeRef.current=changeZoom;
 useEffect(()=>{
  const el=scroll.current;if(!el)return;
  let measured=600;const observer=new ResizeObserver(()=>{if(measured===el.clientWidth)return;measured=el.clientWidth;pending.current??=capture();setWidth(measured);});observer.observe(el);
  let frame=0,queued:number|null=null,point:ZoomPoint|undefined,gestureScale=1,gesturing=false,anchor:Anchor|undefined,idle:ReturnType<typeof setTimeout>;
  const queue=(n:number,p?:ZoomPoint)=>{if(!anchor||p?.x!==point?.x||p?.y!==point?.y)anchor=capture(p);queued=clampZoom(n);point=p;clearTimeout(idle);if(!gesturing)idle=setTimeout(()=>{anchor=undefined;},ZOOM_IDLE_MS);if(!frame)frame=requestAnimationFrame(()=>{frame=0;const next=queued;queued=null;if(next!==null)changeRef.current(String(next),point,anchor);});};
  const wheel=(e:WheelEvent)=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();if(gesturing)return;const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?el.clientHeight:1);queue((queued??current.current.scale)*Math.exp(-Math.max(-100,Math.min(100,delta))*.005),{x:e.clientX,y:e.clientY});};
  const location=(e:Event)=>{const p=e as Event&{clientX?:number;clientY?:number};return Number.isFinite(p.clientX)&&Number.isFinite(p.clientY)?{x:p.clientX!,y:p.clientY!}:undefined;};
  const start=(e:Event)=>{e.preventDefault();clearTimeout(idle);anchor=undefined;gesturing=true;gestureScale=queued??current.current.scale;};
  const gesture=(e:Event)=>{e.preventDefault();const n=(e as Event&{scale:number}).scale;if(Number.isFinite(n))queue(gestureScale*n,location(e));};
  const end=(e:Event)=>{e.preventDefault();gesturing=false;idle=setTimeout(()=>{anchor=undefined;},ZOOM_IDLE_MS);};
  el.addEventListener('wheel',wheel,{passive:false});el.addEventListener('gesturestart',start,{passive:false});el.addEventListener('gesturechange',gesture,{passive:false});el.addEventListener('gestureend',end,{passive:false});
  return()=>{observer.disconnect();cancelAnimationFrame(frame);clearTimeout(idle);el.removeEventListener('wheel',wheel);el.removeEventListener('gesturestart',start);el.removeEventListener('gesturechange',gesture);el.removeEventListener('gestureend',end);};
 },[]);
 useEffect(()=>{
  let alive=true;let task:ReturnType<typeof import('pdfjs-dist/legacy/build/pdf.mjs')['getDocument']>|undefined;
  void (async()=>{try{
   const bytes=new Uint8Array(size);
   for(let offset=0;offset<size;){const r=await rpc<{data:string}>('reader.pdf',{project,pmid,version,offset});if(!alive)return;const data=atob(r.data);if(!data.length)throw new Error('PDF 读取不完整，请重新打开文献');bytes.set(Uint8Array.from(data,c=>c.charCodeAt(0)),offset);offset+=data.length;setLoading(Math.round(offset/size*100));}
   const lib=await import('pdfjs-dist/legacy/build/pdf.mjs');if(!alive)return;lib.GlobalWorkerOptions.workerSrc=workerUrl;
   task=lib.getDocument({data:bytes,isEvalSupported:false,useSystemFonts:true,useWasm:false,cMapUrl:'/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs/standard_fonts/',wasmUrl:'/pdfjs/wasm/'});const doc=await task.promise;
   const dimensions:PageSize[]=[];
   for(let n=1;n<=doc.numPages;n++){const p=await doc.getPage(n);if(!alive)return;const v=p.getViewport({scale:1});dimensions.push({width:v.width,height:v.height});}
   if(alive){setPdf(doc);setSizes(dimensions);}
  }catch(e){if(alive)setError(message(e));}})();
  return()=>{alive=false;ready.current=false;searchId.current++;void task?.destroy();};
 },[project,pmid,version,size]);
 useLayoutEffect(()=>{
  if(!sizes.length||!scroll.current||!pages.current)return;
  const a=pending.current,el=scroll.current;
  if(a){const n=Math.min(sizes.length,Math.max(1,a.page));const node=pages.current.children[n-1] as HTMLElement;
   const rect=node.getBoundingClientRect(),bounds=el.getBoundingClientRect();
   const offset=a.fraction!==undefined?a.fraction*rect.height:Math.min(a.legacyOffset||0,rect.height);
   el.scrollTop+=rect.top-bounds.top-(a.viewportY??16)+offset;
   el.scrollLeft=a.horizontal!==undefined?el.scrollLeft+rect.left-bounds.left+a.horizontal*rect.width-(a.viewportX??el.clientWidth/2):a.left||0;pending.current=null;
  }
  ready.current=true;save();setZoomInput(String(Math.round(scale*100)));
 },[sizes,scale,zoom,width]);
 function jump(n:number){if(!pdf||!scroll.current||!pages.current)return;const bounded=Math.min(pdf.numPages,Math.max(1,n)),node=pages.current.children[bounded-1] as HTMLElement;scroll.current.scrollTop+=node.getBoundingClientRect().top-scroll.current.getBoundingClientRect().top-16;save();}
 function applyZoom(){const value=Number(zoomInput.replace('%','').trim());if(value===Math.round(scale*100)){setZoomInput(String(value));return;}if(Number.isFinite(value)&&value>0)changeZoom(String(value/100));else setZoomInput(String(Math.round(scale*100)));}
 async function find(){if(!pdf||!query.trim())return;const id=++searchId.current;setFinding(true);setSearched(false);const hits:number[]=[];try{for(let n=1;n<=pdf.numPages;n++){const content=await (await pdf.getPage(n)).getTextContent();if(id!==searchId.current)return;if(content.items.map(x=>'str'in x?x.str:'').join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))hits.push(n);}setFound(hits);setSearched(true);if(hits.length)jump(hits[0]);}catch(e){if(id===searchId.current)setError(message(e));}finally{if(id===searchId.current)setFinding(false);}}
 return <div className="paper-pdf"><div className="paper-pdf-tools">
  <button className="icon-button" aria-label={tr("上一页")} disabled={!pdf||page<=1} onClick={()=>jump(page-1)}><ChevronLeft size={16}/></button>
  <label><input aria-label={tr("PDF 页码")} inputMode="numeric" value={pageInput} onChange={e=>setPageInput(e.target.value)} onBlur={()=>{const n=Number(pageInput);if(Number.isInteger(n)&&n>0)jump(n);else setPageInput(String(page));}} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/> / {pdf?.numPages||'…'}</label>
  <button className="icon-button" aria-label={tr("下一页")} disabled={!pdf||page>=pdf.numPages} onClick={()=>jump(page+1)}><ChevronRight size={16}/></button>
  <button className="icon-button" aria-label={tr("缩小 PDF")} disabled={!pdf||scale<=.1} onClick={()=>changeZoom(String(scale/1.1))}><Minus size={15}/></button>
  <label className="paper-pdf-zoom"><input aria-label={tr("PDF 缩放百分比")} title={tr("10%–800%，也可用触控板捏合或 Ctrl/Command + 滚轮缩放")} inputMode="decimal" disabled={!pdf} value={zoomInput} onChange={e=>setZoomInput(e.target.value)} onBlur={applyZoom} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/>%</label>
  <button className="icon-button" aria-label={tr("放大 PDF")} disabled={!pdf||scale>=8} onClick={()=>changeZoom(String(scale*1.1))}><Plus size={15}/></button>
  <button className="text-button" disabled={!pdf} onClick={()=>changeZoom('fit')}>{tr("适合宽度")}</button>
  <form onSubmit={e=>{e.preventDefault();void find();}}><input aria-label={tr("搜索 PDF 文字")} placeholder={tr("查找文字")} value={query} onChange={e=>{setQuery(e.target.value);setSearched(false);}}/><button className="icon-button" aria-label={tr("查找")} disabled={!pdf||finding||!query.trim()}><Search size={15}/></button></form>
 </div>{searched&&<div className="paper-search-results">{found.length?<>{tr("匹配页：")}{found.map(n=><button key={n} className="text-button" onClick={()=>jump(n)}>{n}</button>)}</>:<>{tr("没有匹配文字（扫描件可能没有文字层）")}</>}</div>}{error&&<p role="alert" className="wb-alert">{tr(error)}</p>}
 <div className="paper-pdf-scroll" ref={scroll} onScroll={save}>{!pdf&&<p className="quiet">{tr("正在读取 PDF…")}{loading}%</p>}<div className="paper-pdf-pages" ref={pages}>{pdf&&sizes.map((s,i)=><PdfPage key={i} pdf={pdf} number={i+1} size={s} scale={scale} renderScale={renderScale??scale} root={scroll.current}/>)}</div></div></div>;
}
