import {useEffect,useState} from 'react';
import {Modal} from './ui';
import {rpc,message,stamp} from './research-api';
import {useApp} from './context';
import ReviewBody,{type BodyBlock} from './ReviewBody';

type Manuscript={id:string;created:number;label:string;topic:string;partial:boolean};
export default function ReviewManuscripts({projectId,name,onClose}:{projectId:string;name:string;onClose:()=>void}){
 const {notify}=useApp();const [items,setItems]=useState<Manuscript[]>([]),[selected,setSelected]=useState(''),[preview,setPreview]=useState<{markdown:string;displayBlocks:BodyBlock[]}|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
 useEffect(()=>{let live=true;void rpc<Manuscript[]>('review.writing.manuscripts',{project:projectId,name}).then(v=>{if(live){setItems(v);setSelected(v[0]?.id||'');}}).catch(e=>{if(live)setError(message(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[projectId,name]);
 useEffect(()=>{setPreview(null);if(!selected)return;let live=true;void rpc<{markdown:string;displayBlocks:BodyBlock[]}>('review.writing.manuscript',{project:projectId,name,id:selected}).then(v=>{if(live)setPreview(v);}).catch(e=>{if(live)setError(message(e));});return()=>{live=false;};},[projectId,name,selected]);
 async function exportFile(format:string){setBusy(true);setError('');try{const result=await rpc<{path:string}>('review.writing.manuscript.export',{project:projectId,name,id:selected,format});notify(`稿件已导出：${result.path}`);}catch(e){setError(message(e));}finally{setBusy(false);}}
 return <Modal className="manuscripts-modal" title="已保存稿件" subtitle="每份稿件保留当时的大纲、正文与引用图表，可独立查看和导出。" onClose={onClose}>
 {error&&<p className="wb-alert" role="alert">{error}</p>}
 <div className="manuscripts-layout"><nav aria-label="已保存稿件列表">{items.map(item=><button key={item.id} className={selected===item.id?'selected':''} onClick={()=>setSelected(item.id)}><strong>{item.partial?'草稿':'完整稿'} · {stamp(item.created)}</strong><span>{item.topic}</span></button>)}{!items.length&&<p className="quiet">{loading?'正在读取稿件…':'暂无已保存稿件。生成正文后会自动留存。'}</p>}</nav><section>{selected&&<div className="review-toolbar">{[['md','Markdown'],['docx','Word'],['html','HTML · 引用详情']].map(([format,label])=><button className="button secondary compact" disabled={busy||!preview} key={format} onClick={()=>void exportFile(format)}>{label}</button>)}</div>}{preview?<div className="writing-markdown"><ReviewBody markdown={preview.markdown} blocks={preview.displayBlocks}/></div>:selected?<p className="quiet">正在读取稿件…</p>:null}</section></div>
 </Modal>;
}
