import {evidenceMarkdownComponents} from './evidenceMarkdown';
import {useState} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {rpc,message} from './research-api';
import './evidence-resources.css';
export type EvidenceResource={id:string;kind:'table'|'figure';pmid:string;documentVersion:string;content:string;lineStart:number;lineEnd:number;context:{content:string;lineStart:number;lineEnd:number}[];assetPath?:string;imageError?:string};
function Resource({resource:r,projectId}:{resource:EvidenceResource;projectId:string}){
 const [url,setUrl]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 async function load(){if(url||loading||!r.assetPath)return;setLoading(true);try{const result=await rpc<{dataUrl:string}>('vector.resource',{project:projectId,resourceId:r.id});setUrl(result.dataUrl);setError('');}catch(e){setError(message(e));}finally{setLoading(false);}}
 const htmlTable=r.kind==='table'&&r.content.toLowerCase().includes('<table')?new DOMParser().parseFromString(r.content,'text/html').querySelector('table'):null;
 return <details className="evidence-resource" onToggle={e=>{if(e.currentTarget.open&&r.kind==='figure')void load();}}><summary>{r.kind==='table'?'完整表格':'关联图片'} · 行 {r.lineStart}–{r.lineEnd}</summary><p className="quiet small">按原文位置关联 · PMID {r.pmid}</p>
 {r.kind==='table'?<div className="resource-table">{htmlTable?<table><tbody>{Array.from(htmlTable.rows).map((row,i)=><tr key={i}>{Array.from(row.cells).map((cell,j)=><td key={j} colSpan={cell.colSpan} rowSpan={cell.rowSpan}>{cell.textContent}</td>)}</tr>)}</tbody></table>:<Markdown remarkPlugins={[remarkGfm]} components={evidenceMarkdownComponents}>{r.content}</Markdown>}</div>:<>{url&&<img src={url} alt="原文关联图片"/>}{loading&&<p>正在读取图片…</p>}{(error||r.imageError)&&<p className="wb-inline-error">{error||r.imageError}</p>}</>}
 {!!r.context.length&&<details><summary>前后邻近原文</summary>{r.context.map((p,i)=><div key={i}><small>行 {p.lineStart}–{p.lineEnd}</small><Markdown remarkPlugins={[remarkGfm]} components={evidenceMarkdownComponents}>{p.content}</Markdown></div>)}</details>}
 </details>;
}
export default function EvidenceResources({resources=[],projectId}:{resources?:EvidenceResource[];projectId:string}){
 const unique=[...new Map(resources.map(r=>[r.id,r])).values()];
 return unique.length?<section className="evidence-resources"><h4>关联图表 · {unique.length}</h4>{unique.map(r=><Resource key={r.id} resource={r} projectId={projectId}/>)}</section>:null;
}
