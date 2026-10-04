import {useEffect,useRef,useState} from 'react';
import {FileText,FolderOpen,RefreshCw,Save,Square} from 'lucide-react';
import {useApp} from './context';
import {rpc,message} from './research-api';
import {downloadChanged} from './download-api';
import Select from './Select';
import './markdown.css';

import {useMarkdown,type MarkdownSettingsData as Settings,type MarkdownStatus as Status} from './markdown-api';
const jobLabels:Record<string,string>={queued:'等待转换',running:'转换中',stopping:'正在停止转换',stopped:'已停止',interrupted:'已中断',done:'已完成',failed:'转换失败'};

export function MarkdownPanel(){
 const {project,notify}=useApp();const {data,error:readError}=useMarkdown(project.id);const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [details,setDetails]=useState(false);
 async function load(){try{const s=await rpc<Status>('markdown.status',{project:project.id});setError('');if(s.files.restored||s.files.archived)downloadChanged();}catch(e){setError(message(e));}}
 async function action(op:string,args:Record<string,unknown>={}){setBusy(true);try{const r=await rpc<{count?:number}>('markdown.'+op,{project:project.id,...args});if(op==='start')notify(`已创建本地${args.mode==='clean'?'清洗':'转换'}任务 · ${r.count} 篇`);if(op==='stop')notify('已请求停止；未完成的文献不会发布');await load();downloadChanged();}catch(e){notify(message(e));}finally{setBusy(false);}}
 const running=!!data?.job&&['queued','running','stopping'].includes(data.job.state);
 return <section className="markdown-panel"><div className="markdown-panel-heading"><div><strong><FileText size={17}/>全文 Markdown</strong><p>{data?`${data.pdfCount} 篇当前 PDF · ${data.markdownCount} 篇已转换 · ${data.files.redundant} 篇未纳入的 PDF`:'正在检查项目文件…'}</p></div><div className="download-actions"><button className="button secondary compact" disabled={busy||running||!data?.items.some(i=>i.raw&&!i.needsConversion)} onClick={()=>void action('start',{mode:'clean',pmids:data?.items.filter(i=>i.raw&&!i.needsConversion).map(i=>i.pmid)})}>重新整理文本</button><button className="button primary compact" disabled={busy||running||!data?.ready||!data.pdfCount||data.latestCount===data.pdfCount} onClick={()=>void action('start')}><FileText size={14}/>{data?.pdfCount&&data.latestCount===data.pdfCount?'最新 · 无需转换':'转换当前 PDF'}</button></div></div>
 {(error||readError)&&<p className="wb-inline-error">{error||readError}</p>}{data&&!data.ready&&<p className="wb-inline-error">Marker 尚未准备好，请查看设置中的“全文转换”。</p>}
 {data?.job&&<div className="markdown-job"><span>{jobLabels[data.job.state]||data.job.state} · 成功 {data.job.completed} · 复用 / 跳过 {data.job.skipped} · 失败 {data.job.failed}{data.job.current?` · PMID ${data.job.current}`:''}{data.job.pages?` · 页 ${data.job.page||0}/${data.job.pages}`:''}</span>{running&&<button className="text-button" onClick={()=>void action('stop')}><Square size={12}/>停止转换</button>}{data.job.error&&<p className="wb-inline-error">{data.job.error}</p>}{data.job.items.filter(i=>i.error).slice(-3).map(i=><p key={i.pmid} className="wb-inline-error">PMID {i.pmid}：{i.error}</p>)}</div>}
 <div className="download-actions"><button className="text-button" disabled={busy} onClick={()=>void action('reconcile')}><RefreshCw size={13}/>检查本地文件</button><button className="text-button" onClick={()=>void action('folder',{redundant:true})}><FolderOpen size={13}/>未纳入的 PDF</button><button className="text-button" onClick={()=>void action('folder')}><FolderOpen size={13}/>转换文本文件夹</button>{data?.job&&<button className="text-button" onClick={()=>void action('report')}>转换报告</button>}<button className="text-button" onClick={()=>setDetails(v=>!v)}>{details?'收起':'转换详情'}</button></div>
 {!!data?.files.errors.length&&<p className="wb-inline-error">{data.files.errors.map(x=>`PMID ${x.pmid}：${x.error}`).join('；')}</p>}
 {details&&<div className="markdown-items">{data?.items.filter(i=>i.pdf||i.raw).map(i=><div key={i.pmid}><span>PMID {i.pmid} · {i.markdownState==='latest'?'最新 · 无需转换':i.markdownState==='outdated'?'待更新':'待转换'}{i.engine?` · ${i.engine}`:''}{i.needsConversion?' · 待重新转换':''}{i.layoutRemoved?` · 版面过滤 ${i.layoutRemoved} 项`:''}{i.ready?` · 已清洗 ${i.removed} 项`:''}</span><span>{i.raw&&<button className="text-button" onClick={()=>void action('open',{pmid:i.pmid,raw:true})}>原稿</button>}{i.ready&&<button className="text-button" onClick={()=>void action('open',{pmid:i.pmid})}>整理后文本</button>}</span></div>)}</div>}
 <p className="quiet small">移出项目的文献会保留 PDF，转换文本和检索数据会删除；重新纳入后需再次准备。</p></section>;
}
export function MarkdownSettings(){
 const {project,notify}=useApp();const [data,setData]=useState<Settings|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const currentProject=useRef(project.id);currentProject.current=project.id;
 useEffect(()=>{let live=true;setData(null);void rpc<Settings>('markdown.settings',{project:project.id}).then(d=>{if(live)setData(d);}).catch(e=>{if(live)setError(message(e));});return()=>{live=false;};},[project.id]);
 async function save(){if(!data)return;const target=project.id;setBusy(true);try{const saved=await rpc<Settings>('markdown.settings.save',{project:target,...data.config});if(currentProject.current===target){setData(saved);setError('');}downloadChanged();notify('转换设置已保存');}catch(e){setError(message(e));}finally{setBusy(false);}}
 const cfg=data?.config;
 function change(patch:Partial<Settings['config']>){setData(d=>d?{...d,config:{...d.config,...patch}}:d);}
 return <div className="download-settings"><h2>全文转换</h2>{error&&<div className="wb-alert">{error}</div>}{!data&&!error&&<p className="quiet">正在读取转换设置…</p>}{data&&cfg&&<>
 {!data.ready&&<div className="wb-alert" role="alert">转换环境尚未就绪{data.missing.length?`：缺少 ${data.missing.join('、')}`:''}</div>}
 <div className="conversion-settings wb-form"><label>计算设备<Select aria-label="计算设备" disabled={busy} value={cfg.device} onChange={e=>change({device:e.target.value})}><option value="auto">自动选择</option><option value="cpu">CPU</option><option value="mps">Apple Silicon</option><option value="cuda">NVIDIA GPU</option></Select></label><label>文字提取进程<Select aria-label="文字提取进程" disabled={busy} value={String(cfg.pdftextWorkers)} onChange={e=>change({pdftextWorkers:e.target.value==='auto'?'auto':Number(e.target.value)})}><option value="auto">自动</option>{[1,2,4,8,16].map(n=><option key={n} value={n}>{n}</option>)}</Select></label></div>
 <div className="model-save-bar"><button className="button primary" disabled={busy} onClick={()=>void save()}><Save size={15}/>保存设置</button></div></>}</div>;
}
