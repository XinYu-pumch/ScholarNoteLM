import {t as tr} from './i18n';
import {usePanelFocus} from './usePanelFocus';
import Field from './Field';
import {requestNavigation} from './navigation';
import {useUnsavedChanges} from './useUnsavedChanges';
import {ReaderLink} from './Reader';
import ReviewManuscripts from './ReviewManuscripts';
import {Modal} from './ui';
import {useQuery} from './useQuery';
import {usePageState,useScrollMemory} from './page-memory';
import ModelPicker from './ModelPicker';
import EvidenceResources,{type EvidenceResource} from './EvidenceResources';
import NumberInput from './NumberInput';
import {useEffect,useRef,useState,type CSSProperties} from 'react';
import ReviewBody,{type BodyBlock} from './ReviewBody';
import {BookOpen,Check,ChevronRight,PanelLeft,SlidersHorizontal,FileText,FolderOpen,LoaderCircle,Play,RefreshCw,Save,Square,X} from 'lucide-react';
import {rpc,peekRpc,message} from './research-api';
import {useApp} from './context';
import ActionMenu from './ActionMenu';
import StageMenu from './StageMenu';

type Row={id:string;serial:string;title:string};
type Config={concurrency:number;topK:number;language:string;requirements:string;profileId:string;model:string;contextChars:number;limitContext:boolean};
type Unit={id:string;serial:string;title:string;nodes:string[];leafIds:string[];state:string;latest:boolean;promptReady:boolean;hasContent:boolean;error:string;received:number;reasoningCharacters:number;revision:string};
type Stage={state:string;completed:number;total:number;shortfalls?:number};
type Status={stages?:{preparation:Stage;writing:Stage};materialModel?:string;projectModel?:string;materialModelChanged?:boolean;draftCount?:number;outlineChanged?:boolean;hasContent?:boolean;currentOutlineCount?:number;manuscriptCount?:number;modelLabel?:string;fileRevision:string;config:Config;rows:Row[];units:Unit[];job:{mode?:string;state?:string;phase?:string;error?:string;total?:number;completed?:number;failed?:number;pending?:number;running?:number;cancelled?:number;settled?:number};latest:number;total:number;model:string;runtimeReady:boolean;prepared:number;retrieval:{config:{method:string;};apiModel:string;apiVerified:boolean};effectiveCandidateK:number};
type Chunk={evidenceId?:string;retrievedFor?:string[];resources?:EvidenceResource[];id:string;text:string;metadata:{pmid:string;title:string;sourceKind:string;sectionPath:string[]}};
type Section={sharedEvidence?:Chunk[]|null;sections?:{node_id:string;markdown:string;displayBlocks?:BodyBlock[]}[];evidence?:Record<string,{query:string;chunks:Chunk[]}>;model?:string};
const labels:Record<string,string>={pending:'待生成',retrieving:'检索中',retrieved:'等待撰写',writing:'撰写中',validating:'引用校验',latest:'最新',done:'已完成',outdated:'待更新',failed:'失败',cancelled:'已取消'};
const active=(s?:string)=>['queued','running','stopping'].includes(s||'');
export default function ReviewWriting({projectId,name,visible,outlineRevision,outlineBusy,onActive}:{projectId:string;name:string;visible:boolean;outlineRevision:number;outlineBusy:boolean;onActive:(value:boolean)=>void}){
 const {notify,openSettings}=useApp();
 const [data,setData]=useState<Status|null>(()=>peekRpc<Status>('review.writing.status',{project:projectId,name})||null),[cfg,setCfg]=useState<Config|null>(()=>peekRpc<Status>('review.writing.status',{project:projectId,name})?.config||null),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [selected,setSelected]=usePageState(`${projectId}:writing:${name}:selected`,''),[section,setSection]=useState<Section|null>(()=>peekRpc<Section>('review.writing.section',{project:projectId,name,nodeId:selected})||null),[preview,setPreview]=useState<{markdown:string;displayBlocks?:BodyBlock[]}|null>(null),[evidenceOpen,setEvidenceOpen]=useState(false);
 useEffect(()=>{const dismiss=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!event.defaultPrevented&&!document.querySelector('dialog[open], [role="listbox"]')&&evidenceOpen&&window.matchMedia('(max-width:1399px)').matches)setEvidenceOpen(false);};window.addEventListener('keydown',dismiss);return()=>window.removeEventListener('keydown',dismiss);},[evidenceOpen]);
 const [objectTarget,setObjectTarget]=useState('');
 const [settingsOpen,setSettingsOpen]=useState(false),[citationPmid,setCitationPmid]=useState('');
 const [treeOpen,setTreeOpen]=usePageState(`${projectId}:writing:${name}:treeOpen`,true),[treeWidth,setTreeWidth]=usePageState(`${projectId}:writing:${name}:treeWidth`,240),[collapsed,setCollapsed]=usePageState<string[]>(`${projectId}:writing:${name}:collapsed`,[]);
 const evidencePanel=useRef<HTMLElement>(null);usePanelFocus(evidenceOpen&&preview===null,evidencePanel);
 const layout=useRef<HTMLDivElement>(null);
 const bodyScroll=useRef<HTMLElement>(null);useScrollMemory(`${projectId}:writing:${name}:${preview?'preview':selected}:scroll`,bodyScroll,!!data?.rows.length);
 useEffect(()=>setCitationPmid(''),[selected,preview]);
 const [savedOpen,setSavedOpen]=useState<'complete'|'drafts'|null>(null),[confirm,setConfirm]=useState<'prepare'|'reset'|null>(null);
 const live=useRef(true),requestId=useRef(0),selectionId=useRef(0),dirtyRef=useRef(dirty);dirtyRef.current=dirty;
 const running=active(data?.job.state),unit=data?.units.find(u=>u.nodes.includes(selected)),row=data?.rows.find(r=>r.id===selected);
 const selectedSection=section?.sections?.find(s=>s.node_id===selected);
 const body=selectedSection?.markdown;
 const evidence=section?.evidence?.[selected];
 const shared=Array.isArray(section?.sharedEvidence),shownChunks=shared?section!.sharedEvidence!:evidence?.chunks;
 const recalledIds=new Set(evidence?.chunks?.map(c=>c.id)||[]);
 async function request<T>(op:string,args:Record<string,unknown>={}):Promise<T>{return rpc<T>('review.writing.'+op,{project:projectId,name,...args});}
 const stateQuery=useQuery<Status>('review.writing.status',{project:projectId,name},running?1500:15000,1500,d=>active(d.job.state),visible||running);
 useEffect(()=>{const d=stateQuery.data;if(!d)return;setData(d);if(!dirtyRef.current)setCfg(d.config);onActive(active(d.job.state));setSelected(s=>d.rows.some(r=>r.id===s)?s:d.rows.find(r=>d.units.some(u=>u.hasContent&&u.nodes.includes(r.id)))?.id||d.rows.find(r=>d.units.some(u=>u.leafIds.includes(r.id)))?.id||d.rows[0]?.id||'');},[stateQuery.data]);
 useEffect(()=>{if(stateQuery.error)setError(stateQuery.error);},[stateQuery.error]);

 async function loadSection(id:string){const seq=++selectionId.current;const d=await request<Section>('section',{nodeId:id});if(live.current&&seq===selectionId.current)setSection(d);}
 useEffect(()=>{live.current=true;if(visible)void request<Status>('status').catch(e=>live.current&&setError(message(e)));return()=>{live.current=false;requestId.current++;selectionId.current++;onActive(false);};},[projectId,name,outlineRevision,visible]);
 useEffect(()=>{if(!visible)return;if(!selected){setSection(null);return;}setSection(peekRpc<Section>('review.writing.section',{project:projectId,name,nodeId:selected})||null);void loadSection(selected).catch(e=>setError(message(e)));},[selected,unit?.state,unit?.revision,outlineRevision,visible]);

 useEffect(()=>{let current=true;if(visible&&preview!==null)void request<{markdown:string;displayBlocks?:BodyBlock[]}>('preview').then(d=>{if(current&&live.current)setPreview(d);}).catch(e=>{if(current)setError(message(e));});return()=>{current=false;};},[data?.fileRevision,visible,preview!==null]);
 useEffect(()=>{if(!objectTarget||!preview)return;const target=document.getElementById(objectTarget);if(target)target.scrollIntoView({block:'start'});else setError('对应图表未出现在当前预览中，请刷新后重试。');setObjectTarget('');},[objectTarget,preview]);
 async function openObject(anchor:string){await execute(async()=>{const value=await request<{markdown:string;displayBlocks?:BodyBlock[]}>('preview');if(live.current){setPreview(value);setObjectTarget(anchor);}});}
 async function execute(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();}catch(e){if(live.current)setError(message(e));}finally{if(live.current)setBusy(false);}}
 function edit<K extends keyof Config>(key:K,value:Config[K]){if(cfg){setCfg({...cfg,[key]:value});setDirty(true);}}
 async function start(ids?:string[],op:'start'|'prepare'|'prepare.resume'|'retry'='start',confirmed=false){await execute(async()=>{const d=await request<Status>(op,{config:cfg,unitIds:ids,confirm:confirmed});if(!live.current)return;setData(d);setCfg(d.config);setDirty(false);onActive(active(d.job.state));setPreview(null);setSection(null);selectionId.current++;setConfirm(null);if(!active(d.job.state))notify(op.startsWith('prepare')?'本轮写作材料已准备完成':'所有章节均已完成，无需重新撰写');});}
 async function saveSettings(){
  if(!cfg)return;
  const d=await request<Status>('settings',cfg);setData(d);setCfg(d.config);setDirty(false);setSettingsOpen(false);notify('撰写参数已保存',{tone:'success'});
 }
 const draftDialog=useUnsavedChanges({label:'撰写设置',dirty,busy,save:saveSettings,discard:()=>{if(data)setCfg(data.config);setDirty(false);setSettingsOpen(false);setError('');}});
 const closeSettings=()=>requestNavigation(()=>setSettingsOpen(false));
 const chapterCount=new Set(data?.units.flatMap(u=>u.nodes)||[]).size;
 const completedChapters=new Set(data?.units.filter(u=>u.latest).flatMap(u=>u.nodes)||[]).size;
 const rewriteScope=data?.rows.filter(r=>unit?.nodes.includes(r.id)).map(r=>`${r.serial} ${r.title}`).join('、')||'';
 const blocked=busy||running||outlineBusy;
 const hasContent=data?.hasContent??data?.units.some(u=>u.hasContent)??false;
 async function reset(){await execute(async()=>{const d=await request<Status>('reset',{confirm:true});setData(d);setCfg(d.config);setDirty(false);setPreview(null);setSection(null);selectionId.current++;setConfirm(null);notify('撰写已重置，已保存稿件和导出文件保留');});}
 const needsPreparation=!!data&&(!!data.outlineChanged||data.prepared!==data.total||!data.total);
 const preparation=data?.stages?.preparation;
 const canResumePreparation=preparation?.state==='partial';
 const prepRunning=running&&data?.job.mode==='prepare',writeRunning=running&&data?.job.mode==='write';
 const cancel=()=>void execute(async()=>{setData(await request<Status>('cancel'));});
 const startReason=outlineBusy?'大纲正在更新，完成后可继续。':busy?'正在处理当前操作。':dirty?'请先保存或放弃撰写设置中的修改。':!data?'正在读取撰写状态。':!(data.currentOutlineCount??data.total)?'请先生成或导入综述大纲。':needsPreparation&&!data.runtimeReady?'请先完成文献检索模型设置。':!needsPreparation&&!data.model?'请在撰写设置中选择模型。':'';
 function prepareNew(){if(hasContent)setConfirm('prepare');else void start(undefined,'prepare');}
 return <div className="review-writing">{draftDialog}
 {savedOpen&&<ReviewManuscripts projectId={projectId} name={name} drafts={savedOpen==='drafts'} onClose={()=>setSavedOpen(null)}/>}
 {confirm&&<Modal title={confirm==='prepare'?tr("准备新一轮撰写？"):tr("重置当前撰写？")} onClose={()=>{if(!busy)setConfirm(null);}}><p>{hasContent?tr("完整正文保存到“已保存稿件”，不完整正文保存到“历史草稿”；随后清除本轮进度与材料。"):tr("将清除本轮准备材料和写作进度。")}{confirm==='prepare'?tr("接着重新准备写作材料。"):tr("之后可重新准备材料并撰写。")}</p><p className="quiet">{tr("大纲、写作设置、已保存稿件和导出文件保留。")}</p>{error&&<p className="wb-alert" role="alert">{tr(error)}</p>}<div className="modal-actions"><button data-dialog-autofocus className="button secondary" disabled={busy} onClick={()=>setConfirm(null)}>{tr("取消")}</button><button className={`button primary ${confirm==='reset'?'danger':''}`} disabled={busy} onClick={()=>confirm==='prepare'?void start(undefined,'prepare',true):void reset()}>{busy?tr("正在处理…"):confirm==='prepare'?tr("保存并开始新一轮"):hasContent?tr("保存草稿并重置"):tr("重置撰写")}</button></div></Modal>}

 {error&&!settingsOpen&&<div className="wb-alert" role="alert">{tr(error)}<button className="text-button" onClick={()=>setError('')}>{tr("关闭")}</button></div>}
 {!data||!cfg?<div className="review-generation"><LoaderCircle className="spin" size={18}/>{tr("正在载入撰写工作台…")}</div>:<>
 {settingsOpen&&<Modal title={tr("撰写设置")} className="writing-settings-modal" onClose={closeSettings}>
 <h3>{tr("正文生成")}</h3><div className="writing-fields writing-primary-fields"><ModelPicker label={tr("撰写模型")} value={{profileId:cfg.profileId,model:cfg.model||''}} disabled={blocked} onChange={value=>{setCfg({...cfg,...value});setDirty(true);}}/><label>{tr("并发数")}<NumberInput aria-label={tr("撰写并发数")} type="number" min={1} value={cfg.concurrency} disabled={blocked} onChange={e=>edit('concurrency',Number(e.target.value))}/></label><label>{tr("每节参考片段数")}<NumberInput aria-label={tr("每节参考片段数")} type="number" min={1} value={cfg.topK} disabled={blocked} onChange={e=>edit('topK',Number(e.target.value))}/></label></div><details className="review-extra writing-more-settings"><summary><ChevronRight size={14}/>{tr("高级设置")}</summary> <label className="writing-budget-toggle"><input type="checkbox" checked={!!cfg.limitContext} disabled={blocked} onChange={e=>edit('limitContext',e.target.checked)}/>{tr("限制每次发送的材料长度")}</label>{cfg.limitContext&&<div className="writing-fields"><label>{tr("材料长度上限 · 字符")}<NumberInput aria-label={tr("材料长度上限 · 字符")} type="number" min={12000} max={500000} step={1000} value={cfg.contextChars} disabled={blocked} onChange={e=>edit('contextChars',Number(e.target.value))}/></label></div>}<p className="quiet small">{tr("默认发送全部材料。开启限制后，材料过长时会暂停并提示调整，不会自动截断。")}</p><Field className="writing-requirements">{tr("额外要求")}<textarea aria-label={tr("正文额外要求")} rows={3} maxLength={15000} disabled={blocked} placeholder={tr("论述重点、篇幅倾向、证据边界、写作风格…")} value={cfg.requirements} onChange={e=>edit('requirements',e.target.value)}/></Field>
 <button className="text-button" onClick={()=>void execute(async()=>{await rpc('review.writing.open-prompts',{project:projectId,name});})}><FolderOpen size={14}/>{tr("查看工作文件")}</button></details>

 {error&&<p className="wb-inline-error" role="alert">{tr(error)}</p>}
 <div className="modal-actions"><button className="button secondary" disabled={busy} onClick={closeSettings}>{tr("取消")}</button><button className="button primary" disabled={blocked||!dirty} onClick={()=>void execute(saveSettings)}><Save size={14}/>{tr("保存设置")}</button></div></Modal>}
 <div className="writing-control-bar"><div className="action-bar">
 <WritingStageButton phase="prepare" running={prepRunning} stopping={prepRunning&&data.job.state==='stopping'} complete={!needsPreparation} disabled={busy||outlineBusy||dirty||!data.currentOutlineCount||(!prepRunning&&(running||!data.runtimeReady||!needsPreparation))} label={preparation?.state==='stale'?'更新写作材料':canResumePreparation?'重试失败项':'准备写作材料'} onClick={prepRunning?cancel:()=>canResumePreparation?void start(undefined,'prepare.resume'):prepareNew()}/>
 <WritingStageButton phase="write" running={writeRunning} stopping={writeRunning&&data.job.state==='stopping'} complete={!!data.total&&data.latest===data.total} disabled={busy||outlineBusy||dirty||(!writeRunning&&(running||needsPreparation||!data.model||data.latest===data.total))} label={data.stages?.writing.state==='partial'?'重试失败项':'撰写综述'} onClick={writeRunning?cancel:()=>void start()}/>
 <button className="button secondary" onClick={()=>setSettingsOpen(true)}><SlidersHorizontal size={16}/>{tr("撰写设置")}</button>
 <ActionMenu label={tr("撰写更多操作")}><button disabled={blocked||dirty||!(data.currentOutlineCount??data.total)||!data.runtimeReady} onClick={prepareNew}><FileText size={14}/>{tr("准备新一轮材料")}</button><button disabled={blocked||dirty||!hasContent||data.outlineChanged||data.prepared!==data.total} onClick={()=>void start(data.units.map(u=>u.id))}><RefreshCw size={14}/>{tr("全部重新撰写")}</button><button onClick={()=>setSavedOpen('drafts')}>{tr("历史草稿")}{data.draftCount?` · ${data.draftCount}`:''}</button><button onClick={()=>void execute(async()=>{await request('open-tasks');})}>{tr("任务记录")}</button><button className="danger" disabled={blocked} onClick={()=>setConfirm('reset')}>{tr("重置撰写")}</button></ActionMenu></div></div>
 {!running&&startReason&&<p id="writing-start-reason" className="writing-action-reason">{startReason}{!data.runtimeReady&&<button className="text-button" onClick={()=>openSettings('vectors')}>{tr("检查模型设置")}</button>}</p>}

 {data.outlineChanged&&<p className="writing-stale" role="status">{tr("正文与当前大纲不一致，需重新撰写。旧正文已保留；恢复对应大纲后可继续使用。")}</p>}
 <div className="writing-progress"><div className="action-bar"><button className="icon-button" aria-label={treeOpen?tr("收起章节目录"):tr("展开章节目录")} aria-expanded={treeOpen} onClick={()=>setTreeOpen(!treeOpen)}><PanelLeft size={16}/></button><button className="text-button" disabled={busy} aria-pressed={preview!==null} onClick={()=>{if(preview!==null)setPreview(null);else void execute(async()=>{setPreview(await request<{markdown:string;displayBlocks?:BodyBlock[]}>('preview'));});}}><BookOpen size={14}/>{tr("全文预览")}</button><StageMenu label={tr("导出综述")} caption={tr("导出")}>{(['md','docx','html'] as const).map(f=><button key={f} disabled={blocked||!hasContent} onClick={()=>void execute(async()=>{const r=await request<{path:string;partial:boolean}>('export',{format:f});notify(tr("{p0}已导出：{p1}",{p0:r.partial?tr('草稿'):tr('综述'),p1:r.path}));})}>{f==='md'?'Markdown':f==='docx'?'Word':tr("HTML · 引用详情")}</button>)}</StageMenu><button className="text-button" onClick={()=>setSavedOpen('complete')}>{tr("已保存稿件")}{data.manuscriptCount?` · ${data.manuscriptCount}`:''}</button><button className="icon-button" aria-label={tr("打开综述文件夹")} onClick={()=>void execute(async()=>{await rpc('review.open',{project:projectId,name});})}><FolderOpen size={16}/></button></div></div>
 <div className={`writing-stage-progress ${prepRunning?'is-running':''}`}><span>{tr("材料准备")} <b>{preparation?.completed||0} / {preparation?.total||0}</b></span><progress aria-label={tr("材料准备进度")} value={preparation?.completed||0} max={preparation?.total||1}/>{!!preparation?.shortfalls&&<span>{tr("部分标题的可用文本块不足设定数量")}</span>}</div>
 <div className={`writing-stage-progress ${writeRunning?'is-running':''}`}><span>{tr("综述撰写")} <b>{completedChapters} / {chapterCount}</b></span><progress aria-label={tr("全文完成度")} value={completedChapters} max={chapterCount||1}/></div>
 {data.job.error&&<p className="wb-inline-error" role="alert">{tr(data.job.error)}</p>}
 {!data.rows.length?<div className="review-outline-empty"><FileText size={30}/><strong>{tr("先完成综述大纲")}</strong><p>{tr("保存主题与大纲后，即可检索材料并开始撰写。")}</p></div>:<div ref={layout} className={`writing-layout ${evidenceOpen&&!preview?'with-evidence':''} ${treeOpen?'':'tree-hidden'}`} style={{'--writing-tree-width':`${treeWidth}px`} as CSSProperties}>
 {treeOpen&&<><nav className="writing-tree" aria-label={tr("撰写章节")}><h4>{tr("章节目录")}</h4>{data.rows.filter(r=>!collapsed.some(serial=>r.serial.startsWith(serial+'.'))).map(r=>{const u=data.units.find(u=>u.nodes.includes(r.id)),hasChildren=data.rows.some(v=>v.serial.startsWith(r.serial+'.'));return <div key={r.id} className="writing-tree-row" style={{paddingLeft:Math.min(r.serial.split('.').length-1,5)*12}}>{hasChildren?<button className="icon-button tree-fold" aria-label={tr("{p0}章节 {p1}",{p0:collapsed.includes(r.serial)?tr('展开'):tr('折叠'),p1:r.serial})} aria-expanded={!collapsed.includes(r.serial)} onClick={()=>setCollapsed(v=>v.includes(r.serial)?v.filter(x=>x!==r.serial):[...v,r.serial])}><ChevronRight size={12}/></button>:<span className="tree-fold-spacer"/>}<button title={tr(`${r.serial} ${r.title}${u?` · ${labels[u.state]||u.state}`:''}`)} aria-current={r.id===selected&&!preview?'location':undefined} className={`writing-node ${r.id===selected&&!preview?'selected':''}`} onClick={()=>{setSelected(r.id);setPreview(null);}}><span className="writing-tree-number">{r.serial}</span><span className="writing-tree-title">{r.title}</span>{u&&<span className={`writing-state-dot state-${u.state}`} aria-label={tr(labels[u.state]||u.state)}>{u.latest?<Check size={12}/>:u.state==='failed'?'!':'·'}</span>}</button></div>;})}</nav><div className="writing-divider" role="separator" aria-label={tr("调整章节目录宽度")} aria-orientation="vertical" aria-valuenow={treeWidth} aria-valuemin={180} aria-valuemax={360} tabIndex={0} onKeyDown={e=>{if(e.key==='Home'||e.key==='End'){e.preventDefault();setTreeWidth(e.key==='Home'?180:360);}if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();setTreeWidth(w=>Math.max(180,Math.min(360,w+(e.key==='ArrowLeft'?-12:12))));}}} onPointerDown={e=>e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId)&&layout.current)setTreeWidth(Math.max(180,Math.min(360,e.clientX-layout.current.getBoundingClientRect().left)));}}/></>}

 <article ref={bodyScroll} className="writing-body"><div className="writing-body-toolbar"><h3>{preview!==null?tr("完整综述预览"):`${row?.serial||''} ${row?.title||''}`}</h3><div className="review-toolbar">{preview===null&&unit&&<button className="text-button" title={tr("同时重写：{p0}",{p0:rewriteScope})} disabled={blocked||data.outlineChanged||!unit.promptReady||dirty} onClick={()=>void start([unit.id])}><RefreshCw size={13}/>{tr("重写本组章节")}</button>}{preview===null&&<button className="text-button" onClick={()=>{setCitationPmid('');setEvidenceOpen(!evidenceOpen);}}>{evidenceOpen?tr("收起证据"):tr("查看证据")}</button>}</div></div>
 {unit?.error&&!preview&&<p className="wb-inline-error">{tr(unit.error)}</p>}
 {unit&&['writing','validating'].includes(unit.state)&&!preview&&<div className="writing-live"><LoaderCircle className="spin" size={15}/>{tr(labels[unit.state])}</div>}
 {unit?.hasContent&&!unit.latest&&!data.outlineChanged&&!running&&!preview&&<p className="writing-stale">{tr("写作材料或设置已变化，正文需要更新。")}</p>}
 {preview!==null||body?<div className="writing-markdown"><ReviewBody markdown={preview?.markdown??body??''} blocks={preview?.displayBlocks??(preview===null?selectedSection?.displayBlocks:undefined)} onObjectLink={anchor=>void openObject(anchor)} onCitation={preview===null?pmid=>{setCitationPmid(pmid);setEvidenceOpen(true);}:undefined}/></div>:<div className="writing-placeholder"><FileText size={28}/><p>{unit?tr("此处将显示该小节的综述正文。"):tr("本章包含以下小节")}</p>{!unit&&<div className="writing-child-sections">{data.rows.filter(r=>r.serial.startsWith((row?.serial||'')+'.')&&r.serial.split('.').length===(row?.serial.split('.').length||0)+1).map(r=><button key={r.id} onClick={()=>setSelected(r.id)}><span>{r.serial}</span>{r.title}<ChevronRight size={14}/></button>)}</div>}</div>}
 </article>
 {evidenceOpen&&preview===null&&<button className="writing-backdrop" aria-label={tr("关闭综述证据面板")} onClick={()=>setEvidenceOpen(false)}/>}
 {evidenceOpen&&preview===null&&<aside ref={evidencePanel} className="writing-evidence" aria-label={tr("综述引用原文")}><button className="icon-button writing-evidence-close" aria-label={tr("收起综述证据")} onClick={()=>setEvidenceOpen(false)}><X size={16}/></button><h4>{tr("引用原文")}<span>{shownChunks?.filter(c=>!citationPmid||c.metadata.pmid===citationPmid).length||0}</span></h4>{evidence?.query&&<details className="writing-query"><summary>{tr("查找内容")}</summary><p>{evidence.query}</p></details>}<p className="quiet small">{shared?tr("本组章节使用的参考原文。"):tr("可对照原文核对正文。")}</p>{citationPmid&&<div className="writing-citation-filter"><span>PMID {citationPmid}</span><button className="text-button" onClick={()=>setCitationPmid('')}>{tr("全部原文")}</button></div>}{shownChunks?.filter(c=>!citationPmid||c.metadata.pmid===citationPmid).map((c,i)=><details className="writing-evidence-card" key={`${c.id}:${citationPmid}`} open={!!citationPmid}><summary><span>{c.evidenceId||i+1}</span><div><strong>{c.metadata.title}</strong><small>PMID {c.metadata.pmid} · {c.metadata.sourceKind==='fulltext'?tr("全文"):tr("摘要")}</small></div></summary>{shared&&<p className="quiet small">{recalledIds.has(c.id)?tr("来自当前小节"):tr("来自同组其他小节")} {tr("· 来源小节")}{c.retrievedFor?.join('、')}</p>}<ReaderLink pmid={c.metadata.pmid}/><small>{c.metadata.sectionPath.join(' › ')}</small><p>{c.text}</p>{shared?!!c.resources?.length&&<p className="quiet small">{tr("关联")}{c.resources.length} {tr("个图表，见下方完整资源。")}</p>:<EvidenceResources resources={c.resources} projectId={projectId} review={{name,nodeId:selected}}/>}</details>)}{shared&&<EvidenceResources resources={shownChunks?.filter(c=>!citationPmid||c.metadata.pmid===citationPmid).flatMap(c=>c.resources||[])} projectId={projectId} review={{name,nodeId:selected}}/>} {citationPmid&&!shownChunks?.some(c=>c.metadata.pmid===citationPmid)&&<p className="quiet small">{tr("当前小节未保存该引用的原文片段。")}<ReaderLink pmid={citationPmid}/></p>} {!shownChunks?.length&&<p className="quiet small">{evidence?.query?tr("未找到相关原文。"):tr("准备写作材料后，可在此查看参考原文。")}</p>}</aside>}
 </div>}
 </>}
 </div>;
}

function WritingStageButton({phase,running,stopping,complete,disabled,label,onClick}:{phase:'prepare'|'write';running:boolean;stopping:boolean;complete:boolean;disabled:boolean;label:string;onClick:()=>void}){
 const stop=phase==='prepare'?'停止准备':'停止撰写';
 return <button className={`button writing-stage-button ${complete?'secondary':'primary'} ${running?'is-running':''}`} disabled={disabled||stopping||complete&&!running} aria-label={tr(stopping?'正在停止…':running?stop:complete?phase==='prepare'?'写作材料就绪':'综述撰写完毕':label)} onClick={onClick}>
 {running?<LoaderCircle size={15} className="spin"/>:complete?<Check size={15}/>:phase==='prepare'?<FileText size={15}/>:<Play size={15}/>}
 {running&&!stopping?<><span className="stage-running-label">{tr(phase==='prepare'?'正在准备材料…':'正在撰写综述…')}</span><span className="stage-stop-label">{tr(stop)}</span></>:<span>{tr(stopping?'正在停止…':complete?phase==='prepare'?'写作材料就绪':'综述撰写完毕':label)}</span>}
 </button>;
}
