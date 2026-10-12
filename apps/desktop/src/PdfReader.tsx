import {useEffect,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,Search} from 'lucide-react';
import {rpc,message} from './research-api';
import type {PDFDocumentProxy,RenderTask} from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';

export type ReadingPosition={page?:number;zoom?:string;scroll?:number;pdfVersion?:string;thread?:string};
export default function PdfReader({project,pmid,version,size,position,onPosition}:{project:string;pmid:string;version:string;size:number;position:ReadingPosition;onPosition:(v:ReadingPosition)=>void}){
 const [pdf,setPdf]=useState<PDFDocumentProxy|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(0);
 const [page,setPage]=useState(position.pdfVersion===version?position.page||1:1),[zoom,setZoom]=useState(position.pdfVersion===version?position.zoom||'fit':'fit');
 const [query,setQuery]=useState(''),[found,setFound]=useState<number[]>([]),[finding,setFinding]=useState(false),[searched,setSearched]=useState(false);
 const canvas=useRef<HTMLCanvasElement>(null),layer=useRef<HTMLDivElement>(null),scroll=useRef<HTMLDivElement>(null),[width,setWidth]=useState(600);
 const searchId=useRef(0),initialScroll=useRef(position.pdfVersion===version?position.scroll||0:0),onSave=useRef(onPosition);onSave.current=onPosition;
 useEffect(()=>{const el=scroll.current;if(!el)return;const observer=new ResizeObserver(()=>setWidth(el.clientWidth));observer.observe(el);return()=>observer.disconnect();},[]);
 useEffect(()=>{
  let alive=true;let task:ReturnType<typeof import('pdfjs-dist/legacy/build/pdf.mjs')['getDocument']>|undefined;
  void (async()=>{try{
   const bytes=new Uint8Array(size);
   for(let offset=0;offset<size;){const r=await rpc<{data:string}>('reader.pdf',{project,pmid,version,offset});if(!alive)return;const data=atob(r.data);if(!data.length)throw new Error('PDF 读取不完整，请重新打开文献');bytes.set(Uint8Array.from(data,c=>c.charCodeAt(0)),offset);offset+=data.length;setLoading(Math.round(offset/size*100));}
   const lib=await import('pdfjs-dist/legacy/build/pdf.mjs');if(!alive)return;lib.GlobalWorkerOptions.workerSrc=workerUrl;
   task=lib.getDocument({data:bytes,isEvalSupported:false,useSystemFonts:true,useWasm:false,cMapUrl:'/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'/pdfjs/standard_fonts/',wasmUrl:'/pdfjs/wasm/'});const doc=await task.promise;
   if(alive){setPage(p=>Math.min(Math.max(1,p),doc.numPages));setPdf(doc);}
  }catch(e){if(alive)setError(message(e));}})();
  return()=>{alive=false;searchId.current++;void task?.destroy();};
 },[project,pmid,version,size]);
 useEffect(()=>{
  if(!pdf||!canvas.current||!layer.current)return;
  let alive=true,render:RenderTask|undefined,textLayer:InstanceType<typeof import('pdfjs-dist/legacy/build/pdf.mjs')['TextLayer']>|undefined;
  void (async()=>{try{
   const p=await pdf.getPage(page);if(!alive)return;const natural=p.getViewport({scale:1});const scale=zoom==='fit'?Math.max(.2,(width-32)/natural.width):Number(zoom);
   const viewport=p.getViewport({scale}),el=canvas.current!,text=layer.current!,ratio=Math.min(window.devicePixelRatio||1,2);
   el.width=Math.ceil(viewport.width*ratio);el.height=Math.ceil(viewport.height*ratio);el.style.width=`${viewport.width}px`;el.style.height=`${viewport.height}px`;
   text.replaceChildren();text.style.setProperty('--scale-factor',String(scale));text.style.setProperty('--total-scale-factor',String(scale));
   render=p.render({canvas:el,viewport,transform:ratio===1?undefined:[ratio,0,0,ratio,0,0]});await render.promise;if(!alive)return;
   const {TextLayer}=await import('pdfjs-dist/legacy/build/pdf.mjs');if(!alive)return;textLayer=new TextLayer({textContentSource:p.streamTextContent(),container:text,viewport});await textLayer.render();
   if(alive&&scroll.current){scroll.current.scrollTop=initialScroll.current;initialScroll.current=0;setError('');}
  }catch(e){if(alive)setError(message(e));}})();
  return()=>{alive=false;render?.cancel();textLayer?.cancel();};
 },[pdf,page,zoom,width]);
 useEffect(()=>{onSave.current({page,zoom,pdfVersion:version});},[page,zoom,version]);
 async function find(){if(!pdf||!query.trim())return;const id=++searchId.current;setFinding(true);setSearched(false);const hits:number[]=[];try{for(let n=1;n<=pdf.numPages;n++){const content=await (await pdf.getPage(n)).getTextContent();if(id!==searchId.current)return;if(content.items.map(x=>'str'in x?x.str:'').join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))hits.push(n);}setFound(hits);setSearched(true);if(hits.length)setPage(hits[0]);}catch(e){if(id===searchId.current)setError(message(e));}finally{if(id===searchId.current)setFinding(false);}}
 return <div className="paper-pdf"><div className="paper-pdf-tools"><button className="icon-button" aria-label="上一页" disabled={!pdf||page<=1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={16}/></button><label><input aria-label="PDF 页码" type="number" min={1} max={pdf?.numPages||1} value={page} onChange={e=>{const p=Number(e.target.value);if(pdf&&p>=1&&p<=pdf.numPages)setPage(p);}}/> / {pdf?.numPages||'…'}</label><button className="icon-button" aria-label="下一页" disabled={!pdf||page>=pdf.numPages} onClick={()=>setPage(p=>p+1)}><ChevronRight size={16}/></button><select aria-label="PDF 缩放" value={zoom} onChange={e=>setZoom(e.target.value)}><option value="fit">适合宽度</option>{[.75,1,1.25,1.5,2].map(z=><option key={z} value={z}>{z*100}%</option>)}</select><form onSubmit={e=>{e.preventDefault();void find();}}><input aria-label="搜索 PDF 文字" placeholder="查找文字" value={query} onChange={e=>{setQuery(e.target.value);setSearched(false);}}/><button className="icon-button" aria-label="查找" disabled={!pdf||finding||!query.trim()}><Search size={15}/></button></form></div>{searched&&<div className="paper-search-results">{found.length?<>匹配页：{found.map(n=><button key={n} className="text-button" onClick={()=>setPage(n)}>{n}</button>)}</>:<>没有匹配文字（扫描件可能没有文字层）</>}</div>}{error&&<p role="alert" className="wb-alert">{error}</p>}<div className="paper-pdf-scroll" ref={scroll} onScroll={e=>onSave.current({scroll:e.currentTarget.scrollTop})}>{!pdf&&<p className="quiet">正在读取 PDF… {loading}%</p>}<div className="paper-pdf-page"><canvas ref={canvas} aria-label={`论文 PDF 第 ${page} 页`}/><div ref={layer} className="textLayer"/></div></div></div>;
}
