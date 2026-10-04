import {useEffect,useRef,useState} from 'react';
import {useApp} from './context';
import {rpc,message,stamp,changed} from './research-api';
import {useQuery} from './useQuery';
import {Modal} from './ui';
import ZoteroCollections,{ancestors,canonicalSelection,type Collection} from './ZoteroCollections';
import {CheckCircle2,Folder,X} from 'lucide-react';
import './zotero-import.css';

type Row={key:string;title:string;doi:string;status:string;pmids?:string[];error?:string;pdf?:{state:string;message:string}};
export type ZoteroJob={id:string;state:string;stage:string;created:number;collection:Collection;selectedCollections?:Collection[];total:number;processed:number;matched:number;pdfImported:number;pdfReused:number;sourceId?:string;runId?:string;error?:string;rows:Row[]};
type Preview={id:string;total:number;withDoi:number;uniqueDois:number;collections:Collection[]};
export const zoteroStates:Record<string,string>={queued:'等待启动',running:'导入中',completed:'已完成',partial:'部分完成',cancelled:'已取消',failed:'失败',interrupted:'已中断'};
const results:Record<string,string>={missing_doi:'无有效 DOI，已跳过',pending:'等待匹配',matched:'已匹配',unmatched:'PubMed 无精确匹配',ambiguous:'多个精确匹配，待核对',request_failed:'请求失败'};
export function ZoteroReport({job}:{job:ZoteroJob}){
 const counts=(job.rows||[]).reduce<Record<string,number>>((a,r)=>({...a,[r.status]:(a[r.status]||0)+1}),{});
 return <div className="zotero-report"><p>{job.collection.path} · {stamp(job.created)}</p>{job.selectedCollections&&job.selectedCollections.length>1&&<ul className="zotero-report-folders">{job.selectedCollections.map(c=><li key={c.key}>{c.path}</li>)}</ul>}<p>文献条目 {job.total} · 纳入文献 {job.matched} · 新增 PDF {job.pdfImported} · 已有 PDF {job.pdfReused}</p><p className="quiet small">{Object.entries(counts).map(([k,v])=>`${results[k]||k} ${v}`).join(' · ')}</p>{job.error&&<p role="alert" className="wb-alert">{job.error}</p>}<div className="zotero-report-table"><table><thead><tr><th>条目 / DOI</th><th>PubMed 匹配</th><th>PDF</th></tr></thead><tbody>{(job.rows||[]).map(r=><tr key={r.key}><td>{r.title}<small>{r.doi||'—'} · {r.key}</small></td><td>{results[r.status]||r.status}<small>{r.pmids?.join(', ')}{r.error&&` · ${r.error}`}</small></td><td>{r.pdf?.message||(r.status==='matched'?(job.state==='running'?'等待处理':'未处理'):'—')}</td></tr>)}</tbody></table></div></div>;
}
export function useZoteroJob(onChange?:()=>void){
 const {project}=useApp();const {data:job,error}=useQuery<ZoteroJob|null>('zotero.status',{project:project.id},5000,1500,j=>!!j&&['queued','running'].includes(j.state));
 const last=useRef('');const callback=useRef(onChange);callback.current=onChange;
 useEffect(()=>{const mark=`${project.id}:${job?.id}:${job?.sourceId}:${job?.runId}:${job?.state}`;if(last.current&&last.current!==mark){changed();callback.current?.();window.dispatchEvent(new Event('downloads-changed'));}last.current=mark;},[project.id,job?.id,job?.sourceId,job?.runId,job?.state]);
 return {job,error};
}
export function ZoteroProgress({onChange}:{onChange?:()=>void}){
 const {project}=useApp();const {job,error}=useZoteroJob(onChange);
 const [open,setOpen]=useState(false),[cancelError,setCancelError]=useState('');
 if(!job)return error?<p className="wb-alert">Zotero 任务状态读取失败：{message(error)}</p>:null;
 const active=['queued','running'].includes(job.state);
 return <section className="zotero-progress" aria-label="Zotero 导入任务"><div><strong>Zotero · {zoteroStates[job.state]||job.state}</strong><span>{job.collection.path}</span><p role="status">{job.stage} · 已匹配 {job.matched} 篇 · 新增 PDF {job.pdfImported} / 复用 {job.pdfReused}</p></div><div className="heading-actions"><button className="button secondary compact" onClick={()=>setOpen(true)}>导入报告</button>{active&&<button className="button secondary compact" onClick={()=>{void rpc('zotero.cancel',{project:project.id,id:job.id}).then(()=>setCancelError('已请求取消，已保存的来源和 PDF 将保留。')).catch(e=>setCancelError(message(e)));}}>取消导入</button>}</div>{cancelError&&<p>{cancelError}</p>}{job.error&&<p className="wb-alert">{job.error}</p>}{open&&<Modal title="Zotero 导入报告" onClose={()=>setOpen(false)}><ZoteroReport job={job}/></Modal>}</section>;
}
type PickerMemory={selected:string[];expanded:string[]};
function remember(key:string):PickerMemory{
 try{const v=JSON.parse(localStorage.getItem(key)||'{}');return {selected:Array.isArray(v.selected)?v.selected.filter((k:unknown)=>typeof k==='string'):[],expanded:Array.isArray(v.expanded)?v.expanded.filter((k:unknown)=>typeof k==='string'):[]};}catch{return {selected:[],expanded:[]};}
}
export default function ZoteroImport({onClose,onStarted}:{onClose:()=>void;onStarted:()=>void}){
 const {project}=useApp();const memoryKey=`scholar-zotero-picker:${project.id}`;
 const [collections,setCollections]=useState<Collection[]>([]),[selected,setSelected]=useState<string[]>(()=>remember(memoryKey).selected),[expanded,setExpanded]=useState<string[]>(()=>remember(memoryKey).expanded),[search,setSearch]=useState(''),[preview,setPreview]=useState<Preview|null>(null),[busy,setBusy]=useState(true),[connected,setConnected]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(connected)try{localStorage.setItem(memoryKey,JSON.stringify({selected,expanded}));}catch{}},[memoryKey,selected,expanded,connected]);
 async function load(){setBusy(true);setConnected(false);setError('');setPreview(null);try{const r=await rpc<{collections:Collection[]}>('zotero.collections',{project:project.id});const memory=remember(memoryKey),keys=canonicalSelection(memory.selected,r.collections);setCollections(r.collections);setSelected(keys);setExpanded([...new Set([...memory.expanded,...r.collections.filter(c=>keys.includes(c.key)).flatMap(c=>ancestors(c,r.collections))])]);setConnected(true);}catch(e){setError(message(e));}finally{setBusy(false);}}
 useEffect(()=>{setSearch('');void load();},[project.id]);
 function select(keys:string[]){setSelected(keys);setPreview(null);}
 async function scan(){setBusy(true);setError('');setPreview(null);try{setPreview(await rpc<Preview>('zotero.preview',{project:project.id,collections:selected}));}catch(e){setError(message(e));}finally{setBusy(false);}}
 async function start(){if(!preview)return;setBusy(true);setError('');try{await rpc('zotero.start',{project:project.id,preview:preview.id});changed();onStarted();onClose();}catch(e){setError(message(e));}finally{setBusy(false);}}
 const roots=collections.filter(c=>selected.includes(c.key)),covered=collections.filter(c=>selected.includes(c.key)||ancestors(c,collections).some(k=>selected.includes(k))).length;
 return <Modal className="zotero-import-modal" title="导入自 Zotero" subtitle="选择文件夹，导入其中的文献及可用 PDF。包含全部子文件夹。" onClose={()=>{if(!busy)onClose();}}>
  <div className="zotero-picker-layout">
   <ZoteroCollections collections={collections} selected={selected} expanded={expanded} search={search} disabled={busy||!connected} onSearch={setSearch} onSelect={select} onExpand={setExpanded}/>
   <section className="zotero-selection-pane"><div className="zotero-selection-heading"><h3>导入范围 <span>{roots.length}</span></h3><button className="text-button" disabled={busy||!roots.length} onClick={()=>select([])}>清空选择</button></div>
    <div className="zotero-selected-folders">{roots.length?roots.map(c=><div key={c.key} className="zotero-selected-folder"><Folder size={17}/><div><strong>{c.name}</strong><small>{c.path}</small></div><button aria-label={`移除 ${c.path}`} disabled={busy} onClick={()=>select(selected.filter(k=>k!==c.key))}><X size={15}/></button></div>):<p className="quiet">在左侧勾选文件夹，可跨分支多选。</p>}</div>
    <p className="quiet small">{roots.length?`包含子文件夹后共 ${covered} 个文件夹。重复文献只导入一次。`:'搜索名称可以快速定位文件夹，匹配结果会保留上级目录。'}</p>
    <button className="button secondary" disabled={busy||!connected||!roots.length} onClick={()=>void scan()}>{busy&&connected?'正在处理…':preview?'重新读取文献':'读取所选文献'}</button>
    {!preview&&<p className="quiet small" role="status">请先读取所选文献，检查 DOI 数量后再开始导入。</p>}
    {preview&&<div className="zotero-preview" role="status"><strong>{preview.collections.length} 个文件夹 · {preview.total} 个文献条目</strong><p>有效 DOI {preview.withDoi} 条，去重后 {preview.uniqueDois} 个。</p><p>无有效 DOI {preview.total-preview.withDoi} 条将跳过。</p><p>{preview.uniqueDois?'匹配 PubMed 后，文献和可用 PDF 将加入项目。':'没有有效 DOI，无法开始导入。'}</p></div>}
    <p className="zotero-import-note">仅导入能在 PubMed 匹配的文献。没有 DOI 的条目会跳过。</p>
   </section>
  </div>
  {error&&<p className="wb-alert" role="alert">{error}</p>}
  {!connected&&!busy&&<p className="quiet small">请打开 Zotero，并在高级设置中启用本地 API。连接地址使用“设置 → PDF 下载”中的 Zotero 地址。</p>}
  <div className="zotero-picker-footer"><div className="zotero-connection">{connected&&<CheckCircle2 size={15}/>}<span>{connected?'已连接 Zotero':busy?'正在连接 Zotero…':'尚未连接'}</span><button className="text-button" disabled={busy} onClick={()=>void load()}>重新连接</button></div><div className="heading-actions"><button className="button secondary" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy||!connected||!preview?.uniqueDois} onClick={()=>void start()}>开始导入</button></div></div>
 </Modal>;
}
