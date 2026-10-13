import {t as tr} from './i18n';
import {LanguageSwitch} from './LanguageControls';
import {useLocale} from './i18n';
import Field from './Field';
import DraftModal,{DraftCancel} from './DraftModal';
import {requestNavigation} from './navigation';
import {Notification} from './Notification';
import {useScrollMemory} from './page-memory';
import {useQuery} from './useQuery';
import {rpc,message} from './research-api';
import {useDownloads} from './download-api';
import {useMarkdown} from './markdown-api';
import {useVectors} from './Vector';
import {currentDownload,taskActive,taskWaits,type Pipeline} from './task-state';
import DownloadTasks from './Downloads';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, ChevronRight, CircleHelp, FileText, Folder, ListTodo, Menu, MessageSquare, Moon, Plus, Search, Settings, SquarePen, Sun, Trash2 } from 'lucide-react';
import { Provider, useApp } from './context';
import type { Page, Project } from './data';
import Library from './Library';
import SearchWorkbench from './SearchWorkbench';
import ResearchSettings from './ResearchSettings';
import { Reader } from './Workspace';
import Chat from './LiteratureQA';
import Review from './Review';
import { Empty, IconButton, Modal } from './ui';

const nav = [
  { id: 'search' as Page, label: '检索工作台', icon: Search },
  { id: 'library' as Page, label: '文献库', icon: BookOpen },
  { id: 'review' as Page, label: '综述工作台', icon: SquarePen },
  { id: 'chat' as Page, label: '文献问答', icon: MessageSquare },
  { id: 'reader' as Page, label: '阅读与笔记', icon: FileText },
];
export default function App() { useLocale();return <Provider><ProjectRoot /></Provider>; }
function ProjectRoot() {
  const {state,toast,dismissToast}=useApp();
  const [creating,setCreating]=useState(false);
  if(state.projects.length)return <Shell />;
  return <div className="boot-screen"><div className="boot-language"><LanguageSwitch/></div><img src="/mark.svg" alt="" /><h2>{tr("还没有研究项目")}</h2><p>{tr("创建一个项目，开始整理文献与笔记。")}</p><button className="button primary" onClick={()=>setCreating(true)}><Plus size={16}/>{tr("创建新项目")}</button>{creating&&<NewProject onClose={()=>setCreating(false)}/ >}<Notification notice={toast} onClose={dismissToast}/></div>;
}
function Shell() {
  const { state, project, page, setPage, updateState, toast, dismissToast, saveStatus, retrySave, notify } = useApp();
  const [projectMenu, setProjectMenu] = useState(false);
  const [deletingProject,setDeletingProject]=useState(false);
  const [newProject, setNewProject] = useState(false);
  const [globalSearch, setGlobalSearch] = useState(false);
  const [help, setHelp] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const {data:downloads}=useDownloads(project.id);
  const {data:taskMarkdown}=useMarkdown(project.id);
  const {data:taskVectors}=useVectors(project.id);
  const taskFlow=useQuery<{job:Pipeline|null}>('library.status',{project:project.id},10000,1500,d=>taskActive(d.job?.state)).data?.job;
  const taskDownload=currentDownload(downloads.batches,project.id);
  const pendingTasks=taskWaits(taskFlow,taskDownload,taskMarkdown?.job,taskVectors?.job);
  const running = Number(taskActive(taskDownload?.state)||!!pendingTasks.download)
    +Number(taskActive(taskMarkdown?.job?.state)||!!pendingTasks.markdown)
    +Number(taskActive(taskVectors?.job?.state)||!!pendingTasks.index);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setGlobalSearch(s => !s); } if (e.metaKey && !e.altKey && !e.shiftKey && (e.code === 'Comma' || e.key === ',')) { e.preventDefault(); go('settings'); } if (e.key === 'Escape') { setProjectMenu(false); setMobileNav(false); } };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, []);
  const mainScroll=useRef<HTMLElement>(null);useScrollMemory(`${project.id}:${page}:scroll`,mainScroll);
  useEffect(()=>{mainScroll.current?.focus({preventScroll:true});},[project.id,page]);
  function go(next: Page) { setPage(next); setMobileNav(false); }
  return <div className="app-shell" onClickCapture={e=>{const button=(e.target as Element).closest<HTMLButtonElement>('button:not(:disabled)');button?.focus({preventScroll:true});}}><a className="skip-link" href="#main">{tr("跳至主内容")}</a>{mobileNav && <button className="nav-backdrop" aria-label={tr("关闭导航")} onClick={() => setMobileNav(false)} />}<aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}><button className="brand" aria-label={tr("ScholarNoteLM · 文献库")} title={tr("文献库")} onClick={() => go('library')}><img src="/mark.svg" alt="" /><span>ScholarNote<span>LM</span></span></button><div className="workspace-label">{tr("当前研究项目")}</div><div className="project-switcher-wrap"><button className="project-switcher" title={project.name} aria-label={tr("切换项目：{p0}",{p0:project.name})} aria-expanded={projectMenu} onClick={() => setProjectMenu(!projectMenu)}><span className={`project-avatar ${project.color}`}><Folder size={18} /></span><span><strong>{project.name}</strong><small>{tr("研究项目")}</small></span><ChevronDown size={14} /></button>{projectMenu && <><button className="menu-dismiss" aria-label={tr("关闭项目菜单")} onClick={() => setProjectMenu(false)} /><div className="project-menu"><div className="eyebrow">{tr("切换项目")}</div>{state.projects.map(p => <button key={p.id} onClick={() => { if(p.id===project.id)go('library');else updateState(s => ({ ...s, active: p.id })); setProjectMenu(false); }}><span className={`project-dot ${p.color}`} /><span>{p.name}</span>{p.id === project.id && <Check size={14} />}</button>)}<button className="project-create" onClick={() => { setProjectMenu(false); requestNavigation(()=>setNewProject(true)); }}><Plus size={16} />{tr("创建新项目")}</button><button className="project-delete" onClick={()=>{setProjectMenu(false);requestNavigation(()=>setDeletingProject(true));}}><Trash2 size={16}/>{tr("删除当前项目")}</button></div></>}</div><button aria-label={tr("搜索你的研究")} title={tr("搜索你的研究 · ⌘ K")} className="sidebar-search" onClick={() => setGlobalSearch(true)}><Search size={15} /><span>{tr("搜索你的研究")}</span><kbd>⌘ K</kbd></button><div className="nav-label">{tr("工作区")}</div><nav className="main-nav" aria-label={tr("主导航")}>{nav.map(item => <button key={item.id} aria-label={tr(item.label)} title={tr(item.label)} aria-current={page === item.id?"page":undefined} className={page === item.id?'active':''} onClick={() => go(item.id)}><item.icon size={18} strokeWidth={1.65} /><span>{tr(item.label)}</span>{item.id === 'library' && <small>{project.papers.length}</small>}{page === item.id && <i />}</button>)}</nav><div className="sidebar-bottom"><button aria-label={tr("任务中心")} title={tr("任务中心")} className={page === 'tasks'?'active':''} onClick={() => go('tasks')}><ListTodo size={17} /><span>{tr("任务中心")}</span>{running > 0 && <span className="task-count">{running}</span>}</button><button aria-label={tr("设置")} title={tr("设置")} className={page === 'settings'?'active':''} onClick={() => go('settings')}><Settings size={17} /><span>{tr("设置")}</span></button><div className="sidebar-profile"><span className="profile-avatar">{tr("研")}</span><div><strong>{tr("个人研究空间")}</strong><span>ScholarNoteLM · 0.6.0{import.meta.env.DEV?tr(" · 开发版"):''}</span></div><IconButton icon={CircleHelp} label={tr("使用帮助")} onClick={() => setHelp(true)} /></div></div></aside><div className="app-content"><header className="topbar"><div className="breadcrumbs"><button className="mobile-nav-toggle icon-button" aria-label={tr("打开导航")} onClick={() => setMobileNav(true)}><Menu size={18} /></button><Folder size={15} /><span>{project.name}</span><ChevronRight size={13} /><strong>{tr(nav.find(n => n.id === page)?.label||(page === 'tasks' ? '任务中心' : '设置'))}</strong></div><div className="topbar-right"><LanguageSwitch/><IconButton icon={state.theme === 'light'?Moon:Sun} label={tr("切换主题")} onClick={() => updateState(s => ({ ...s, theme: s.theme === 'light' ? 'dark' : 'light' }))} /></div></header>{saveStatus==='保存失败'&&<div className="wb-alert app-save-error" role="alert">{tr("保存失败，请检查存储位置与磁盘空间。")}<button className="text-button" onClick={()=>void retrySave().catch(e=>notify(message(e),{tone:'error'}))}>{tr("重试保存")}</button></div>}<main ref={mainScroll} id="main" tabIndex={-1} className={`main-content page-${page}`} key={`${project.id}-${page}`}>
    {page === 'search' && <SearchWorkbench />}{page === 'library' && <Library />}{page === 'chat' && <Chat />}{page === 'review' && <Review />}{page === 'reader' && <Reader />}{page === 'tasks' && <DownloadTasks />}{page === 'settings' && <ResearchSettings />}
  </main></div><Notification notice={toast} onClose={dismissToast}/>{deletingProject && <DeleteProject key={project.id} onClose={()=>setDeletingProject(false)}/ >}{newProject && <NewProject onClose={() => setNewProject(false)} />}{globalSearch && <GlobalSearch onClose={() => setGlobalSearch(false)} />}{help && <Modal title={tr("欢迎来到 ScholarNoteLM")} subtitle={tr("研究工作台 · v0.6")} onClose={() => setHelp(false)}><div className="help-content"><img src="/mark.svg" alt="" /><h3>{tr("把文献，变成有连接的知识。")}</h3><p>{tr("从 PubMed 检索或 Zotero 导入文献，整理全文、记录笔记，并基于项目文献进行问答和综述撰写。")}</p><div className="help-details"><span><Check size={16} />{tr("开始前，可在设置中连接模型服务。")}</span><span><Check size={16} />{tr("保存位置：设置 → 外观与存储，可查看项目工作目录。")}</span><span><Check size={16} />{tr("在文献库点击“一键更新文献”，准备问答和综述所需的材料。")}</span></div><button className="button primary" onClick={() => setHelp(false)}>{tr("开始探索")}<ArrowRight size={15} /></button></div></Modal>}</div>;
}

function DeleteProject({onClose}:{onClose:()=>void}) {
  const {project,deleteProject,notify}=useApp();
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [projectPath,setProjectPath]=useState('');
  useEffect(()=>{let alive=true;void rpc<{projectPath:string}>('storage.status',{project:project.id}).then(v=>{if(alive)setProjectPath(v.projectPath);}).catch(e=>{if(alive)setError(message(e));});return()=>{alive=false;};},[project.id]);
  async function remove(){
    setBusy(true);setError('');
    try{await deleteProject(project.id);notify('项目及其文件已永久删除');onClose();}catch(e){setError(message(e));}finally{setBusy(false);}
  }
  return <Modal busy={busy} title={tr("删除当前项目")} subtitle={project.name} onClose={()=>{if(!busy)onClose();}}><form onSubmit={e=>{e.preventDefault();void remove();}}><p>{tr("项目内所有文件都将永久删除，包括文献、笔记、综述、已保存稿件和导出文件，无法恢复。")}</p><p className="quiet small">{projectPath||tr("正在读取项目路径…")}</p>{error&&<div className="wb-alert" role="alert">{tr(error)}</div>}<div className="modal-actions"><button type="button" className="button secondary" data-dialog-autofocus disabled={busy} onClick={onClose}>{tr("取消")}</button><button className="button danger" disabled={busy||!projectPath}>{busy?tr("正在删除…"):tr("确认删除项目")}</button></div></form></Modal>;
}

function NewProject({ onClose }: { onClose: () => void }) {
  const { createProject, notify } = useApp();
  const id=useRef(crypto.randomUUID().replaceAll('-',''));
  const [name, setName] = useState(''); const [description, setDescription] = useState(''); const [folder,setFolder]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  async function persist(){
    if(!name.trim())throw new Error('请填写项目名称');
    if(!/^[A-Za-z0-9_㐀-䶿一-鿿]{1,64}$/.test(folder.trim()))throw new Error('文件夹名须为 1–64 个中文、英文、数字或下划线');
    const p:Project={id:id.current,name:name.trim(),description:description.trim(),color:'purple',papers:[],messages:[],sections:[{id:'intro',title:'引言',content:''}],notes:{},tasks:[]};
    await createProject(p,folder.trim());notify('研究项目已创建',{tone:'success'});onClose();
  }
  async function create(){setBusy(true);setError('');try{await persist();}catch(e){setError(message(e));}finally{setBusy(false);}}
  return <DraftModal dirty={!!(name||folder||description)} busy={busy} save={persist} title={tr("开始一项新的研究")} subtitle={tr("一个项目，容纳你的文献、想法与发现。")} onClose={()=>{if(!busy)onClose();}}><form onSubmit={e=>{e.preventDefault();void create();}}><Field className="form-field">{tr("项目名称")}<input disabled={busy} autoFocus required maxLength={60} placeholder={tr("例如：神经炎症与认知功能")} value={name} onChange={e=>setName(e.target.value)}/></Field><Field className="form-field">{tr("项目文件夹名")}<input disabled={busy} required pattern="[A-Za-z0-9_㐀-䶿一-鿿]+" maxLength={64} placeholder={tr("例如：神经炎症_2026")} value={folder} onChange={e=>setFolder(e.target.value)}/><span>{tr("支持中文、英文、数字和下划线；在项目工作目录中创建同名文件夹。")}</span></Field><Field className="form-field">{tr("研究目标")}<span>{tr("可选")}</span><textarea disabled={busy} rows={3} placeholder={tr("你想探索什么问题？")} value={description} onChange={e=>setDescription(e.target.value)}/></Field>{error&&<div className="wb-alert" role="alert">{tr(error)}</div>}<div className="modal-actions"><span className="quiet small">{tr("文献与笔记将在项目间独立保存")}</span><DraftCancel className="button secondary" disabled={busy}>{tr("取消")}</DraftCancel><button className="button primary" disabled={busy||!name.trim()||!folder.trim()}>{busy?tr("正在创建…"):tr("创建项目")}<ArrowRight size={15}/></button></div></form></DraftModal>;
}

function GlobalSearch({ onClose }: { onClose: () => void }) {
  const { project, openPaper, setPage } = useApp(); const [value, setValue] = useState('');
  const results = project.papers.filter(p => `${p.title} ${p.id} ${p.author} ${p.tag}`.toLowerCase().includes(value.toLowerCase())).slice(0, 7);
  return <Modal title={tr("搜索你的研究")} subtitle={tr("当前项目 · {p0}",{p0:project.name})} onClose={onClose}><Field className="search-field global-search-field"><Search size={18} /><input autoFocus aria-label={tr("全局搜索")} value={value} onChange={e => setValue(e.target.value)} placeholder={tr("文献标题、PMID、作者…")} /></Field><div className="global-results">{results.map(p => <button key={p.id} onClick={() => { openPaper(p); onClose(); }}><FileText size={17} /><div><strong>{p.title}</strong><span>{p.journal} · {p.year} {tr("· 阅读与笔记")}</span></div><ArrowUpRight size={14} /></button>)}{!results.length && <Empty title={tr("没有找到文献")} text={tr("试试其他关键词，或先向当前项目添加文献。")} />}</div><div className="search-quick"><button onClick={() => { setPage('chat'); onClose(); }}><MessageSquare size={14} />{tr("文献问答")}</button><button onClick={() => { setPage('review'); onClose(); }}><SquarePen size={14} />{tr("综述工作台")}</button><kbd>{tr("ESC 关闭")}</kbd></div></Modal>;
}
