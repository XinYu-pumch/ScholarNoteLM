import {t as tr} from './i18n';
import {flushSync} from 'react-dom';
import Field from './Field';
import DraftModal,{DraftCancel} from './DraftModal';
import {useDraftGuard} from './useUnsavedChanges';
import {useTabs} from './useTabs';
import {requestNavigation} from './navigation';
import ZoteroImport,{useZoteroJob,zoteroStates,ZoteroReport,type ZoteroJob} from './ZoteroImport';
import QueryFilterBatch from './QueryFilterBatch';
import {needsQueryRun} from './search-proposals';
import {usePageState} from './page-memory';
import Select from './Select';
import ActionMenu from './ActionMenu';
import {useEffect,useRef,useState} from 'react';
import {RefreshCw,Search,Plus,Play,Download,Upload,Sparkles,LibraryBig,Archive,RotateCcw,Check,History,LoaderCircle,Pencil,Square,SlidersHorizontal} from 'lucide-react';
import {useApp} from './context';
import {Modal} from './ui';
import SearchChat from './SearchChat';
import {rpc,peekRpc,changed,stamp,message,exportXml,defaultFilters,type WorkbenchData,type Query,type Run,type Filters,type Proposal} from './research-api';
function validateQuery(q:Query){
 if(!q.name.trim())throw new Error('请填写检索式标题');
 if(!Number.isInteger(q.filters.limit)||q.filters.limit<1||q.filters.limit>10000)throw new Error('目标文献数须为 1–10000 的整数');
 if(q.filters.start&&q.filters.end&&q.filters.start>q.filters.end)throw new Error('开始日期不能晚于结束日期');
}
function FilterFields({value:f,onChange:set,imported=false}:{value:Filters;onChange:(v:Filters)=>void;imported?:boolean}){
 return <><div className="wb-form-grid"><label>{tr("排序方式")}<Select aria-label={tr("排序方式")} disabled={imported} value={f.sort} onChange={e=>set({...f,sort:e.target.value})}><option value="relevance">{tr("相关性")}</option><option value="pub_date">{tr("最新发表")}</option></Select></label><Field>{tr("目标文献数")}<input disabled={imported} type="number" min={1} max={10000} value={f.limit} onChange={e=>set({...f,limit:Number(e.target.value),mode:'explore'})}/></Field></div><details className="wb-advanced" open={!!(f.start||f.end)}><summary>{tr("发表日期")}<span>{f.start||f.end?tr("已设置"):tr("不限日期")}</span></summary><div className="wb-form-grid"><Field>{tr("发表日期 · 开始")}<input disabled={imported} type="date" value={f.start} onChange={e=>set({...f,start:e.target.value})}/></Field><Field>{tr("发表日期 · 结束")}<input disabled={imported} type="date" value={f.end} onChange={e=>set({...f,end:e.target.value})}/></Field></div></details><details className="wb-advanced" open={f.jcr}><summary>{tr("JCR 分区筛选")}<span>{f.jcr?f.quartiles.join(' / '):tr("不限分区")}</span></summary><div className="wb-quartiles">{['Q1','Q2','Q3','Q4'].map(q=><label key={q}><input type="checkbox" checked={f.jcr&&f.quartiles.includes(q)} onChange={e=>{const quartiles=e.target.checked?[...f.quartiles,q]:f.quartiles.filter(v=>v!==q);set({...f,quartiles,jcr:quartiles.length>0});}}/>{q}</label>)}</div><p className="quiet small">{tr("未匹配期刊或无分区的文献不计入目标数量。")}</p><p className="quiet small">{tr("任一学科分区满足即可。取消所有勾选即不限制 JCR。")}</p></details></>;
}
function QueryRow({query:q,busy,job,onCancel,onSave,onEdit,onRun,onArchive,onToggle,onHistory}:{query:Query;busy:boolean;job?:ZoteroJob;onCancel:()=>void;onSave:(q:Query)=>Promise<void>;onEdit:(q:Query)=>void;onRun:(q:Query)=>Promise<void>;onArchive:()=>void;onToggle:()=>void;onHistory:()=>void}){
 const [draft,setDraft]=useState(q);useEffect(()=>setDraft(q),[q.id,q.revision,q.name,JSON.stringify(q.filters)]);
 const dirty=draft.name!==q.name||draft.text!==q.text||JSON.stringify(draft.filters)!==JSON.stringify(q.filters);
 const guard=useDraftGuard({label:tr("检索式「{p0}」",{p0:q.name}),dirty,busy,save:()=>onSave(draft),discard:()=>setDraft(q)});
 const openEdit=()=>{setDraft(q);onEdit(draft);};
 const f=draft.filters;const imported=q.source==='import';
 if(q.source==='zotero'){
  const active=!!job&&['queued','running'].includes(job.state);
  const folders=job?.selectedCollections?.length?job.selectedCollections:q.run?.zotero?.selectedCollections;
  const path=folders?.map(c=>c.path).join('；')||job?.collection.path||q.run?.zotero?.collection.path||q.name;
  const shortName=q.name.startsWith('Zotero · ')?(folders?.map(c=>c.name||c.path.split(' / ').at(-1)).join('、')||(job?.collection.path||q.run?.zotero?.collection.path)?.split(' / ').at(-1)||q.name):q.name;
  return <tr className={`zotero-source-row ${!q.enabled?'disabled':''}`}>
   <td><input type="checkbox" aria-label={tr("启用 {p0}",{p0:q.name})} checked={q.enabled} disabled={busy||active||q.archived} onChange={onToggle}/></td>
   <td><div className="zotero-source-name"><span className="zotero-source-label">Zotero</span><input aria-label={tr("来源名称")} title={tr(draft.name===q.name?shortName:draft.name)} value={draft.name===q.name?shortName:draft.name} disabled={busy||q.archived} onChange={e=>setDraft({...draft,name:e.target.value})}/></div></td>
   <td colSpan={5}><div className="zotero-source-details"><strong title={tr(path)}>{path}</strong><small>{tr("含子文件夹 ·")}{stamp(job?.created||q.run?.created)}</small>{job&&<p role="status">{active?<><LoaderCircle className="spin" size={13}/>{job.stage}</>:job.error||tr(job.stage)}{q.run&&tr(" · PDF 新增 {p0} / 复用 {p1}",{p0:job.pdfImported||0,p1:job.pdfReused||0})}</p>}</div></td>
   <td><div className="zotero-source-status"><span className={`wb-chip ${job&&['partial','failed','interrupted','cancelled'].includes(job.state)?'warn':''}`}>{job?tr(zoteroStates[job.state]||job.state):q.xmlExists?tr("已完成"):tr("结果文件缺失")}</span><small>{q.run?tr("{p0} 篇 · {p1}",{p0:q.run.fetched,p1:q.xmlExists?tr('已保存'):tr('结果文件缺失')}):active?tr("正在准备文献"):tr("文献尚未保存")}</small></div></td>
   <td>{guard.dialog}<div className="query-actions">{dirty&&<button title={tr("保存名称")} onClick={()=>void onSave(draft).catch(()=>{})} disabled={busy||!draft.name.trim()}><Check size={15}/></button>}<button title={tr("导入详情")} onClick={openEdit}><History size={15}/></button>{active?<button title={tr("取消导入")} onClick={onCancel}><Square size={14}/></button>:<button title={q.archived?tr("恢复"):tr("归档")} disabled={busy} onClick={onArchive}>{q.archived?<RotateCcw size={14}/>:<Archive size={14}/>}</button>}</div></td>
  </tr>;
 }

 return <tr className={!q.enabled?'disabled':''} onDoubleClick={e=>{if(!(e.target instanceof HTMLSelectElement)&&!(e.target instanceof HTMLInputElement&&e.target.type==='checkbox'))openEdit();}}>
  <td><input type="checkbox" aria-label={tr("启用 {p0}",{p0:q.name})} checked={q.enabled} disabled={busy||q.archived} onChange={onToggle}/></td>
  <td><input aria-label={tr("检索式标题")} value={draft.name} disabled={busy||q.archived} onChange={e=>setDraft({...draft,name:e.target.value})}/></td>
  <td><input className="query-short" aria-label={tr("检索式内容")} title={draft.text||tr("填写 PubMed 检索式")} placeholder={imported?tr("XML 导入批次"):tr("填写检索式…")} value={draft.text} disabled={imported||busy||q.archived} onChange={e=>setDraft({...draft,text:e.target.value})}/></td>
  <td><Select aria-label={tr("排序方式")} value={f.sort} disabled={imported||busy||q.archived} onChange={e=>setDraft({...draft,filters:{...f,sort:e.target.value}})}><option value="relevance">{tr("相关性")}</option><option value="pub_date">{tr("最新发表")}</option></Select></td>
  <td><input aria-label={tr("目标文献数")} type="number" min={1} max={10000} value={f.limit} disabled={imported||busy||q.archived} onChange={e=>setDraft({...draft,filters:{...f,limit:Number(e.target.value),mode:'explore'}})}/></td>
  <td><button className="query-cell-button" title={tr(`${f.start||tr('不限起始')} — ${f.end||tr('不限结束')}`)} disabled={busy||q.archived} onClick={openEdit}>{f.start||f.end?`${f.start||tr('不限')} → ${f.end||tr('不限')}`:tr("不限日期")}</button></td>
  <td><button className="query-cell-button" disabled={busy||q.archived} onClick={openEdit}>{f.jcr?f.quartiles.join(' / '):tr("不限分区")}</button></td>
  <td><button className={`query-status ${q.stale||q.error?'warn':''}`} title={tr(q.error||`${stamp(q.run?.created)}${q.run?tr(" · 已获取 {p0} 条",{p0:q.run.fetched}):''}`)} onClick={openEdit}>{q.xmlExists?(q.stale?tr('待更新'):q.run?.qualified!=null&&q.run.qualified<q.filters.limit?tr('已完成 · 数量不足'):tr('已完成')):q.run?tr("结果文件缺失"):tr("未执行")}{q.error&&' !'}</button></td>
  <td>{guard.dialog}<div className="query-actions">{dirty?<button aria-label={tr("保存 {p0}",{p0:q.name})} title={tr("保存修改")} disabled={busy||!draft.name.trim()} onClick={()=>void onSave(draft).catch(()=>{})}><Check size={15}/></button>:<button aria-label={tr("编辑 {p0}",{p0:q.name})} title={tr("详情与编辑（也可双击条目）")} disabled={busy} onClick={openEdit}><Pencil size={13}/></button>}{!q.archived&&!imported&&<button aria-label={tr("执行 {p0}",{p0:q.name})} title={tr("保存并执行")} disabled={busy||!q.enabled||!draft.text.trim()||!draft.name.trim()} onClick={()=>void onRun(draft)}><Play size={14}/></button>}{q.run&&<button aria-label={tr("历史 {p0}",{p0:q.name})} title={tr("执行历史")} disabled={busy} onClick={onHistory}><History size={14}/></button>}<button aria-label={tr(`${tr(q.archived?'恢复':'归档')} ${q.name}`)} title={q.archived?tr("恢复"):tr("归档")} disabled={busy} onClick={onArchive}>{q.archived?<RotateCcw size={14}/>:<Archive size={14}/>}</button></div></td>
 </tr>;
}
export default function SearchWorkbench(){
 const {project,notify}=useApp();const [data,setData]=useState<WorkbenchData|null>(()=>peekRpc<WorkbenchData>('workspace',{project:project.id})||null);const [tab,setTab]=usePageState(`${project.id}:search:tab`,'queries');const [busy,setBusy]=useState('');const [error,setError]=useState('');const [edit,setEdit]=useState<Query|null>(null);const [archived,setArchived]=usePageState(`${project.id}:search:archived`,false);const [history,setHistory]=useState<Run[]|null>(null);const [zoteroOpen,setZoteroOpen]=useState(false);const [zoteroReport,setZoteroReport]=useState<ZoteroJob|null>(null);const batch=useRef<AbortController|null>(null);const [batchProgress,setBatchProgress]=useState('');const [stopping,setStopping]=useState(false);const [batchFilters,setBatchFilters]=useState(false);
 useEffect(()=>{if(tab!=='queries'&&tab!=='planning')setTab('queries');},[tab,setTab]);
 useEffect(()=>()=>{batch.current?.abort();},[project.id]);
 const apply=(d:WorkbenchData)=>{setData(d);changed();};
 async function refresh(){setData(await rpc<WorkbenchData>('workspace',{project:project.id}));}
 const {job:zoteroJob,error:zoteroError}=useZoteroJob(()=>void refresh().catch(e=>setError(message(e))));
 const sourceLocked=!!data?.sourceBusy||!!zoteroJob&&['queued','running'].includes(zoteroJob.state);
 async function cancelZotero(){if(!zoteroJob)return;try{await rpc('zotero.cancel',{project:project.id,id:zoteroJob.id});notify('已请求取消，已保存的文献和 PDF 将保留');}catch(e){setError(message(e));}}
 useEffect(()=>{setEdit(null);setBatchFilters(false);void refresh().catch(e=>setError(message(e)));},[project.id]);
 // Commit busy state before save-and-leave continues through the remaining navigation guards.
 async function action(key:string,fn:()=>Promise<void>,propagate=false){setBusy(key);setError('');try{await fn();}catch(e){setError(message(e));if(propagate)throw e;}finally{if(propagate)flushSync(()=>setBusy(''));else setBusy('');}}
 const update=(name:string,args:Record<string,unknown>)=>rpc<WorkbenchData>(name,{project:project.id,...args}).then(apply);
 async function create(){setArchived(false);await update('query.create',{});}
 async function runQueries(draft?:Query,force=false){
  if(batch.current)return;const controller=new AbortController();batch.current=controller;setStopping(false);
  let completed=0;
  try{
   if(draft){validateQuery(draft);await update('query.save',draft);}
   const fresh=await rpc<WorkbenchData>('workspace',{project:project.id});apply(fresh);
   const queries=draft?fresh.queries.filter(q=>q.id===draft.id):fresh.queries.filter(q=>force?q.enabled&&!q.archived&&q.source!=='import'&&q.source!=='zotero'&&!!q.text.trim():needsQueryRun(q));
   if(!queries.length){notify('检索结果无需更新');return;}
   for(let i=0;i<queries.length;i++){
    if(controller.signal.aborted)break;
    const q=queries[i],executionId=crypto.randomUUID();setBusy(`run:${q.id}`);setBatchProgress(tr("正在检索 {p0}/{p1} · {p2}",{p0:i+1,p1:queries.length,p2:q.name}));
    const cancel=()=>{void rpc('query.cancel',{project:project.id,id:q.id,executionId}).catch(e=>setError(tr("中止请求未送达：{p0}",{p0:message(e)})));};
    controller.signal.addEventListener('abort',cancel,{once:true});
    try{const result=await rpc<WorkbenchData>('query.run',{project:project.id,id:q.id,executionId,onlyPending:!draft&&!force,force:force||!!draft});apply(result);if(!controller.signal.aborted)completed++;}
    catch(e){if(!controller.signal.aborted)throw e;await refresh();}
    finally{controller.signal.removeEventListener('abort',cancel);}
    if(controller.signal.aborted)break;
    if(i<queries.length-1){setBatchProgress(tr("已完成 {p0}/{p1} · 等待 2 秒后检索下一条",{p0:i+1,p1:queries.length}));await new Promise<void>(resolve=>{const finish=()=>{clearTimeout(timer);controller.signal.removeEventListener('abort',finish);resolve();};const timer=setTimeout(finish,2000);controller.signal.addEventListener('abort',finish,{once:true});});}
   }
   notify(controller.signal.aborted?'已中止执行，已完成的结果及原有 XML 均已保留':tr("已执行 {p0} 条{p1}",{p0:completed,p1:draft?tr('检索式'):tr('待更新检索式，其余检索结果保持不变')}));
  }finally{batch.current=null;setBatchProgress('');setStopping(false);}
 }
 function stopQueries(){if(batch.current){setStopping(true);batch.current.abort();setBatchProgress('正在中止执行，保留已完成的结果…');}}

 async function addProposal(q:Proposal){await update('query.save',{name:q.name,text:q.text,source:'assistant',filters:defaultFilters()});notify('已加入检索式，默认相关性排序、30 条；可在管理页调整');}
 const tabs=useTabs(tab,['queries','planning'],value=>requestNavigation(()=>setTab(value)));
 if(!data)return <div className="page"><h1>{tr("检索工作台")}</h1>{error?<div className="wb-alert" role="alert">{tr(error)}<button className="text-button" onClick={()=>void refresh().catch(e=>setError(message(e)))}>{tr("重试")}</button></div>:<p className="quiet">{tr("正在读取项目检索策略…")}</p>}</div>;
 const queries=data.queries.filter(q=>q.archived===archived).sort((a,b)=>Number(a.source==='zotero')-Number(b.source==='zotero'));const active=data.queries.filter(q=>q.enabled&&!q.archived);const stale=active.filter(needsQueryRun);
 return <div className={`page workbench-page ${tab==='planning'?'is-chat':''}`}>
  <div className="workbench-heading"><div><h1>{tr("检索工作台")}</h1><span>{active.length} {tr("个启用来源 ·")}{data.corpus.included.toLocaleString()} {tr("篇文献")}</span></div></div>
  <div className="library-tabs wb-tabs"><div role="tablist" aria-label={tr("检索工作台视图")}>{[['queries','文献来源'],['planning','检索助手']].map(([id,label])=><button key={id} {...tabs.tab(id)} className={tab===id?'active':''}>{id==='planning'?<Sparkles size={15}/>:<LibraryBig size={15}/>} {tr(label)}</button>)}</div></div>
  {error&&<div className="wb-alert" role="alert">{tr(error)}<button aria-label={tr("关闭错误")} onClick={()=>setError('')}>×</button></div>}
  {busy&&<div className="wb-working" role="status"><LoaderCircle className="spin" size={15}/>{batchProgress||(busy.startsWith('run:')?tr('正在获取文献信息…'):tr('正在处理…'))}{batch.current&&<button type="button" className="button secondary compact query-stop" disabled={stopping} onClick={stopQueries}><Square size={13}/>{stopping?tr("正在停止…"):tr("停止检索")}</button>}</div>}

  {zoteroError&&<p className="wb-alert">{tr("Zotero 任务状态读取失败：")}{message(zoteroError)}</p>}
  {sourceLocked&&<p className="zotero-source-lock" role="status">{tr("Zotero 导入中，暂时不能更改文献来源或启动下载；可查看文献、导出已保存 XML，或取消导入。")}</p>}
  {zoteroOpen&&<ZoteroImport key={project.id} onClose={()=>setZoteroOpen(false)} onStarted={()=>{void refresh().catch(e=>setError(message(e)));notify('Zotero 来源已创建，离开页面后会继续导入');}}/>}
  {zoteroReport&&<Modal title={tr("Zotero 来源 · 导入报告")} onClose={()=>setZoteroReport(null)}><ZoteroReport job={zoteroJob?.id===zoteroReport.id?zoteroJob:zoteroReport}/><button disabled={!data.queries.find(q=>q.id===zoteroReport.sourceId)?.run?.id} className="button secondary" onClick={()=>void action('export',async()=>notify(tr("XML 已导出：{p0}",{p0:await exportXml(project.id,data.queries.find(q=>q.id===zoteroReport.sourceId)!.run!.id)})))}>{tr("导出来源 XML")}</button></Modal>}
  {tab!=='queries'&&<div {...tabs.panel('queries')} hidden/>}{tab!=='planning'&&<div {...tabs.panel('planning')} hidden/>}
  {tab==='queries'&&<div {...tabs.panel('queries')} className="wb-query-section"><div className="wb-toolbar"><div className="action-bar"><button className="button primary" aria-describedby="query-action-reason" title={stale.length?tr("更新 {p0} 条未执行、条件变化或待补足的检索式",{p0:stale.length}):tr("所有启用检索式均已处理")} disabled={!!busy||sourceLocked||!stale.length} onClick={()=>requestNavigation(()=>void action('all',()=>runQueries()))}><Play size={14}/>{tr("更新检索（")}{stale.length}）</button><button aria-label={tr("添加检索式")} className="button secondary" disabled={!!busy||sourceLocked} onClick={()=>void action('create',create)}><Plus size={16}/>{tr("添加检索式")}</button><button className="button secondary" disabled={!!busy||sourceLocked} onClick={()=>setZoteroOpen(true)}><Upload size={14}/>{tr("导入自 Zotero")}</button><button className="text-button" disabled={!!busy||sourceLocked||!data.queries.some(q=>!q.archived&&q.source!=='zotero')} onClick={()=>requestNavigation(()=>setBatchFilters(true))}><SlidersHorizontal size={14}/>{tr("批量筛选")}</button><button className="text-button" disabled={!!busy||!data.corpus.included} onClick={()=>void action('export',async()=>notify(tr("XML 已导出：{p0}",{p0:await exportXml(project.id)})))}><Download size={14}/>{tr("导出 XML")}</button><ActionMenu label={tr("文献来源更多操作")}><button disabled={!!busy||sourceLocked||!active.some(q=>q.source!=='import'&&q.source!=='zotero'&&q.text.trim())} onClick={()=>requestNavigation(()=>void action('rerun',()=>runQueries(undefined,true)))}><RefreshCw size={14}/>{tr("全部重新检索")}</button><button onClick={()=>requestNavigation(()=>setArchived(!archived))}><Archive size={14}/>{archived?tr("返回当前"):tr("已归档")}</button></ActionMenu>{archived&&<span className="action-context">{tr("已归档来源")}</span>}</div></div>
   <p id="query-action-reason" className="action-reason">{sourceLocked?tr("导入完成后可更新检索"):busy?tr("请等待当前操作完成"):!active.length?tr("请先添加并启用检索式"):!stale.length?tr("所有启用检索式均已处理"):tr("仅更新未执行、条件变化或数量待补足的检索式")}</p><div className="query-table-wrap"><table className="query-table"><colgroup><col className="q-enable"/><col className="q-name"/><col className="q-text"/><col className="q-sort"/><col className="q-count"/><col className="q-date"/><col className="q-jcr"/><col className="q-state"/><col className="q-actions"/></colgroup><thead><tr>{['','来源名称','检索式 / 集合','排序方式','数量','发表日期','JCR 分区','执行状态','操作'].map((title,i)=><th key={i}>{tr(title)}</th>)}</tr></thead><tbody>{queries.map(q=><QueryRow key={q.id} query={q} busy={!!busy||sourceLocked} job={zoteroJob?.sourceId===q.id?zoteroJob:q.zoteroJob} onCancel={()=>void cancelZotero()} onEdit={q=>{if(q.source==='zotero')void action('report',async()=>setZoteroReport(await rpc<ZoteroJob>('zotero.report',{project:project.id,id:q.zoteroJob?.id||q.run?.zotero?.job||q.id})));else setEdit(q);}} onSave={draft=>action('save',async()=>{validateQuery(draft);await update('query.save',draft);},true)} onRun={draft=>action(`run:${q.id}`,()=>runQueries(draft))} onToggle={()=>void action('toggle',()=>update('query.toggle',{id:q.id,value:!q.enabled}))} onArchive={()=>requestNavigation(()=>void action('archive',()=>update('query.archive',{id:q.id,value:!q.archived})))} onHistory={()=>void action('history',async()=>setHistory(await rpc<Run[]>('query.history',{project:project.id,id:q.id})))}/> )}</tbody></table>{!queries.length&&<div className="query-empty"><Search size={25}/><p>{archived?tr("暂无归档条目"):tr("添加检索式，或从 Zotero 集合导入文献。")}</p>{!archived&&<button className="text-button" disabled={sourceLocked} onClick={()=>void action('create',create)}><Plus size={14}/>{tr("添加第一条")}</button>}</div>}</div>
   {stale.length>0&&<p className="wb-footnote">{tr("当前")}{stale.length} {tr("条策略待重新执行。")}</p>}
  </div>}
  {tab==='planning'&&<div {...tabs.panel('planning')} className="search-tab-panel"><SearchChat key={project.id} queries={data.queries} onAdd={addProposal}/></div>}
  {batchFilters&&!sourceLocked&&<QueryFilterBatch queries={data.queries} onClose={()=>setBatchFilters(false)} onApply={async filters=>{await update('query.filters.apply',filters);notify('统一筛选条件已应用，仍可逐条调整');}}/>}
  {edit&&<DraftModal dirty={JSON.stringify(edit)!==JSON.stringify(data.queries.find(q=>q.id===edit.id))} busy={!!busy} save={()=>action('save',async()=>{validateQuery(edit);await update('query.save',edit);setEdit(null);},true)} title={tr("检索式详情")} subtitle={tr("筛选条件仅应用于此条检索式。")} onClose={()=>{if(!busy)setEdit(null);}}><div className="wb-form"><Field>{tr("标题")}<input value={edit.name} disabled={edit.archived} onChange={e=>setEdit({...edit,name:e.target.value})}/></Field><Field>{tr("PubMed 检索式")}<textarea className="wb-code-input" aria-label={tr("PubMed 检索式")} rows={4} value={edit.text} disabled={edit.source==='import'||edit.archived} onChange={e=>setEdit({...edit,text:e.target.value})}/></Field><FilterFields value={edit.filters} imported={edit.source==='import'} onChange={filters=>setEdit({...edit,filters})}/>{edit.run&&<div className="query-run-info"><span>{edit.xmlExists?tr("✓ 结果已保存"):tr("结果文件缺失")} · {stamp(edit.run.created)}</span><p>{tr("命中")}{edit.run.count.toLocaleString()} {tr("· 候选")}{edit.run.fetched} {tr("· 合格")}{edit.run.qualified??tr("待核对")} / {edit.run.target??edit.filters.limit}{edit.run.candidateLimitReached?tr(" · 已达候选获取上限"):edit.run.exhausted&&edit.run.qualified!=null&&edit.run.qualified<edit.filters.limit?tr(" · 候选已查尽，数量不足"):edit.run.truncated?tr(" · 限量结果"):''}</p><button className="text-button" disabled={!!busy} onClick={()=>void action('export-run',async()=>notify(tr("已导出：{p0}",{p0:await exportXml(project.id,edit.run!.id)})))}><Download size={13}/>{tr("导出此条 XML")}</button></div>}{edit.error&&<p className="wb-inline-error">{tr(edit.error)}</p>}{error&&<div className="wb-alert">{tr(error)}</div>}<div className="modal-actions"><DraftCancel className="button secondary" disabled={!!busy}>{tr("取消")}</DraftCancel><button className="button primary" disabled={!!busy||sourceLocked||!edit.name.trim()||edit.archived} onClick={()=>void action('save',async()=>{validateQuery(edit);await update('query.save',edit);setEdit(null);notify('检索式已保存');})}><Check size={15}/>{tr("保存修改")}</button></div></div></DraftModal>}
  {history&&<Modal title={tr("执行历史")} subtitle={tr("查看以往检索结果，或导出 XML。")} onClose={()=>setHistory(null)}><div className="wb-history">{history.map(r=><article key={r.id}><div><strong>{stamp(r.created)}</strong><p>{tr("命中")}{r.count} {tr("· 候选")}{r.fetched} {tr("· 合格")}{r.qualified??tr("历史记录")}{r.truncated?tr(" · 限量结果"):''}</p><code>{r.text}</code></div><button className="button secondary compact" disabled={!!busy} onClick={()=>void action('export-run',async()=>notify(tr("已导出：{p0}",{p0:await exportXml(project.id,r.id)})))}><Download size={14}/>XML</button></article>)}</div></Modal>}
 </div>;
}
