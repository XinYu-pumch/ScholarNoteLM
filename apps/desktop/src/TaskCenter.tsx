import {ZoteroProgress} from './ZoteroImport';
import {useEffect,useId,useState,type ReactNode} from 'react';
import {ChevronDown,Database,Download,FileText,FolderOpen,Pause,Play,RotateCcw,Square} from 'lucide-react';
import {useApp} from './context';
import {rpc,message,stamp} from './research-api';
import {useQuery} from './useQuery';
import {useDownloads,downloadChanged,recoveryLabel,stageLabels,startDownload,retryBloomDownloads} from './download-api';
import {useMarkdown} from './markdown-api';
import {IndexProgress,adaptivePhase,useVectors,ChunkBrowser} from './Vector';
import {Modal} from './ui';
import {currentDownload,downloadHeld,jobElapsed,taskActive,taskDuration,taskResult,taskWaits,type Pipeline} from './task-state';
import './task-center.css';

type CardProps={kind:string;title:string;icon:ReactNode;state:string;status:string;exists:boolean;loading?:boolean;total:number;processed:number;success:number;skipped:number;failed:number;deferred?:number;created?:number;elapsed?:number;phase?:string;error?:string;actions?:ReactNode;progressContent?:ReactNode;children?:ReactNode};
function TaskCard({kind,title,icon,state,status,exists,loading,total,processed,success,skipped,failed,deferred=0,created,elapsed,phase,error,actions,progressContent,children}:CardProps){
 const [expanded,setExpanded]=useState(false),id=useId();
 const percent=total?Math.max(0,Math.min(100,processed/total*100)):0;
 return <section className="task-card" aria-label={title} data-task={kind}>
  <div className="task-card-main">
   <div className="task-card-title"><span className="task-card-icon">{icon}</span><div><h2>{title}</h2><p>{created?stamp(created):'当前项目'}{elapsed!==undefined?` · 耗时 ${taskDuration(elapsed)}`:''}</p></div></div>
   <div className="task-card-progress">{exists?<><div className="task-card-progress-label"><span>{phase||'本轮处理'}</span><span>{processed} / {total} 篇</span></div><div className="task-progress-track" role="progressbar" aria-label={`${title}处理进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}><span style={{width:`${percent}%`}}/></div><p>成功 {success} · {kind==='download'?'已有 PDF':'已完成，跳过'} {skipped} · 失败 {failed}{deferred?` · 待重试 ${deferred}`:''}</p></>:<p className="task-idle-note">{loading?'正在读取任务状态…':phase||'从文献库启动后，在此查看进度与结果'}</p>}</div>
   <div className="task-card-controls"><span className={`task-state ${taskActive(state)?'active':state==='failed'?'error':''}`}>{loading?'读取中':status}</span><div className="task-card-actions">{actions}</div></div>
  </div>
  {progressContent}
  {error&&<p className="task-error" role="alert">{error}</p>}
  {children&&<><button className="task-details-toggle" aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(v=>!v)}>{expanded?'收起详情':'查看详情'}<ChevronDown size={14}/></button>{expanded&&<div className="task-card-details" id={id}>{children}</div>}</>}
 </section>;
}

export default function TaskCenter(){
 const {project,notify,setPage}=useApp();
 const {data:downloads,error:downloadError,loading:downloadLoading}=useDownloads(project.id);
 const {data:markdown,error:markdownError}=useMarkdown(project.id);
 const {data:vectors,error:vectorError}=useVectors(project.id);
 const flowQuery=useQuery<{job:Pipeline|null}>('library.status',{project:project.id},10000,1500,d=>taskActive(d.job?.state));
 const flow=flowQuery.data?.job,flowActive=taskActive(flow?.state);
 const batch=currentDownload(downloads.batches,project.id),md=markdown?.job,index=vectors?.job;
 const [busy,setBusy]=useState(''),[report,setReport]=useState<{text:string;path:string}|null>(null),[inspect,setInspect]=useState(false),[now,setNow]=useState(Date.now()/1000);
 const live=taskActive(batch?.state)||taskActive(md?.state)||taskActive(index?.state);
 useEffect(()=>{if(!live)return;const timer=setInterval(()=>setNow(Date.now()/1000),1000);return()=>clearInterval(timer);},[live]);
 async function act(key:string,action:string,args:Record<string,unknown>={}){setBusy(key);try{await rpc(action,{project:project.id,...args});downloadChanged();}catch(e){notify(message(e));}finally{setBusy('');}}
 async function downloadAction(command:string){if(batch)await act('download','download.control',{id:batch.id,command});}
 async function retry(){if(!batch)return;setBusy('download');try{
  // A retry is a new run with its own denominator; original evidence stays in the old batch.
  const available=new Set(markdown?.items.filter(i=>!i.pdf).map(i=>i.pmid));
  const pmids=batch.items.filter(i=>['failed','deferred'].includes(i.state)&&available.has(i.pmid)).map(i=>i.pmid);
  if(!pmids.length)throw new Error('当前项目没有仍缺 PDF 的失败或延期文献');
  if(batch.config.downloadMode==='zotero'){await rpc('download.start',{project:project.id,pmids,mode:'zotero'});downloadChanged();}
  else await startDownload(project.id,pmids);
 }catch(e){notify(message(e));}finally{setBusy('');}}
 async function reportFor(kind:'download'|'vector',folder=false){try{
  const r=await rpc<{text:string;path:string}>(kind+'.report',{project:project.id,...(kind==='download'?{id:batch?.id}:{}),...(folder?{open:true,folder:true}:{})});if(!folder)setReport(r);
 }catch(e){notify(message(e));}}
 const {download:dw,markdown:mdWait,index:indexWait}=taskWaits(flow,batch,md,index);
 const dc=batch?.counts||{},processed=(dc.success||0)+(dc.skipped||0)+(dc.failed||0)+(dc.deferred||0);
 const runningStages=Array.from(new Set(batch?.items.filter(i=>i.state==='running').map(i=>i.stage)||[]));
 const downloadPhase=runningStages.some(s=>s==='pmc_s3'||s==='europe_pmc_getpdf')?'正在从 PMC / Europe PMC 下载':runningStages.map(s=>stageLabels[s]||s).join(' · ');
 const anyDownload=downloadHeld(batch?.state),mdActive=taskActive(md?.state),indexActive=taskActive(index?.state);
 return <div className="page task-center"><ZoteroProgress/><div className="page-heading"><div><h1>任务中心</h1><p>查看文献准备进度与结果</p></div><button className="button secondary" onClick={()=>setPage('library')}><FolderOpen size={15}/>前往文献库</button></div>
  {flowActive&&<div className="task-flow-note"><span>{flow?.mode==='clear'?'正在清理项目数据':flow?.state==='stopping'||flow?.stage==='stopping'?'正在停止一键更新':'一键更新进行中，后续步骤将自动接续'}</span><button className="text-button" disabled={!!busy||flow?.state==='stopping'||flow?.stage==='stopping'} onClick={()=>void act('flow','library.stop')}>停止流程</button></div>}
  {flowQuery.error&&<p role="alert" className="task-error">{flowQuery.error}</p>}
  <div className="task-center-list">
   <TaskCard key={`download:${project.id}:${batch?.id}:${dw}`} kind="download" loading={downloadLoading} title="PDF 下载" icon={<Download size={20}/>} state={dw?'queued':batch?.state||'idle'} status={dw||(!batch?'尚未开始':batch.control?batch.control==='pause'?'正在暂停':'正在取消':taskResult(batch.state,dc.failed,dc.deferred))} exists={!!batch&&!dw} total={batch?.items.length||0} processed={processed} success={dc.success||0} skipped={dc.skipped||0} failed={dc.failed||0} deferred={dc.deferred} created={dw?undefined:batch?.created} elapsed={dw||taskActive(batch?.state)?undefined:batch?.elapsed} phase={dw||downloadPhase} error={downloadError||(!dw?batch?.error:undefined)} actions={!dw&&batch&&<>
    {['queued','running'].includes(batch.state)&&<button className="button secondary compact" disabled={!!busy||!!batch.control} onClick={()=>void downloadAction('pause')}><Pause size={13}/>暂停</button>}
    {['paused','cancelled'].includes(batch.state)&&<button className="button secondary compact" disabled={!!busy||!!batch.control} onClick={()=>void downloadAction('resume')}><Play size={13}/>继续</button>}
    {anyDownload&&<button className="button secondary compact" disabled={!!busy||!!batch.control} onClick={()=>void downloadAction('cancel')}><Square size={13}/>取消</button>}
    {!anyDownload&&((dc.failed||0)+(dc.deferred||0)>0)&&<button className="button secondary compact" disabled={!!busy||flowActive||!markdown} onClick={()=>void retry()}><RotateCcw size={13}/>重试未获取项</button>}
   </>}>
    {batch&&!dw&&<><div className="task-detail-actions"><button className="button secondary compact" onClick={()=>void reportFor('download')}><FileText size={14}/>查看下载报告</button><button className="text-button" onClick={()=>void reportFor('download',true)}>日志文件夹</button>{!!batch.bloomSummary?.hits&&<details className="technical-details"><summary>高级操作</summary><button className="text-button" disabled={!!busy||anyDownload||flowActive} onClick={async()=>{setBusy('download');try{await retryBloomDownloads(project.id);}catch(e){notify(message(e));}finally{setBusy('');}}}>重试 Bloom 命中未完成项</button></details>}</div>
     <p className="task-detail-note">{batch.config.downloadMode==='zotero'?'Zotero 本地导入':'标准下载'} · 本轮 {batch.items.length} 篇 · 未完成的文献可稍后重试。</p>
     <div className="task-sources">{Object.entries(batch.items.filter(i=>i.state==='success').reduce<Record<string,number>>((s,i)=>{const key=i.source||'其他来源';s[key]=(s[key]||0)+1;return s;},{})).map(([source,count])=><span key={source}>{source} <b>{count}</b></span>)}</div>
     <div className="task-item-list">{batch.items.map(i=><div key={i.pmid}><div><strong>{i.title||`PMID ${i.pmid}`}</strong><p>PMID {i.pmid} · {i.source||stageLabels[i.stage]||'等待处理'}</p>{i.error&&<p className="task-error">{i.error}</p>}</div><span>{recoveryLabel(i)}</span></div>)}</div></>}
   </TaskCard>
   <TaskCard key={`markdown:${project.id}:${md?.id}:${mdWait}`} kind="markdown" title="全文转换" icon={<FileText size={20}/>} state={mdWait?'queued':md?.state||'idle'} status={mdWait||(!md?'尚未开始':taskResult(md.state,md.failed))} exists={!!md&&!mdWait} loading={!markdown&&!markdownError} total={md?.pmids.length||0} processed={(md?.completed||0)+(md?.skipped||0)+(md?.failed||0)} success={md?.completed||0} skipped={md?.skipped||0} failed={md?.failed||0} created={mdWait?undefined:md?.created} elapsed={mdWait?undefined:jobElapsed(md,now)} phase={mdWait||(md?.current?`PMID ${md.current}${md.pages?` · 第 ${md.page||0} / ${md.pages} 页`:''}`:'')} error={markdownError||(!mdWait?md?.error:undefined)} actions={!mdWait&&mdActive&&<button className="button secondary compact" disabled={!!busy||md?.state==='stopping'} onClick={()=>void act('markdown','markdown.stop')}><Square size={13}/>停止转换</button>}>
    {md&&!mdWait&&<><div className="task-detail-actions"><button className="button secondary compact" onClick={()=>void act('markdown','markdown.report')}><FileText size={14}/>转换报告与日志</button><button className="text-button" onClick={()=>void act('markdown','markdown.folder')}>转换文本文件夹</button></div><p className="task-detail-note">{md.mode==='clean'?'重新整理文本':'全文转换'} · {md.pmids.length} 篇</p><JobItems items={md.items}/></>}
   </TaskCard>
   <TaskCard key={`index:${project.id}:${index?.id}:${indexWait}`} kind="index" progressContent={!indexWait&&<IndexProgress job={index||null}/>} title="检索索引" icon={<Database size={20}/>} state={indexWait?'queued':index?.state||'idle'} status={indexWait||(!index?'尚未开始':taskResult(index.state,index.failed))} exists={!!index&&!indexWait} loading={!vectors&&!vectorError} total={index?.pmids.length||0} processed={(index?.completed||0)+(index?.skipped||0)+(index?.failed||0)} success={index?.completed||0} skipped={index?.skipped||0} failed={index?.failed||0} created={indexWait?undefined:index?.created} elapsed={indexWait?undefined:jobElapsed(index,now)} phase={indexWait||adaptivePhase(index||null)||(index?.current?`PMID ${index.current}${index.totalChunks!=null?` · ${index.embeddedChunks||0} / ${index.totalChunks} 块`:''}`:'')} error={vectorError||(!indexWait?index?.error:undefined)} actions={!indexWait&&indexActive&&<button className="button secondary compact" disabled={!!busy||index?.state==='stopping'} onClick={()=>void act('index','vector.stop')}><Square size={13}/>停止索引</button>}>
    {index&&!indexWait&&<><div className="task-detail-actions"><button className="button secondary compact" onClick={()=>void reportFor('vector')}><FileText size={14}/>查看索引报告</button><button className="text-button" onClick={()=>void reportFor('vector',true)}>日志文件夹</button><button className="text-button" onClick={()=>setInspect(true)}>查看参考片段</button></div><JobItems items={index.items}/></>}
   </TaskCard>
  </div>
  {inspect&&<ChunkBrowser onClose={()=>setInspect(false)}/>}
  {report&&<Modal title="任务报告" subtitle={report.path} onClose={()=>setReport(null)}><pre className="download-report">{report.text}</pre></Modal>}
 </div>;
}
function JobItems({items}:{items:{pmid:string;state:string;error?:string}[]}){
 const labels:Record<string,string>={success:'成功',skipped:'已复用',failed:'失败',running:'处理中',queued:'等待处理',done:'成功'};
 return <div className="task-item-list">{items.length?items.map(i=><div key={i.pmid}><div><strong>PMID {i.pmid}</strong>{i.error&&<p className="task-error">{i.error}</p>}</div><span>{labels[i.state]||i.state}</span></div>):<p className="task-detail-note">尚无逐篇处理结果</p>}</div>;
}
