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
export default function App() { return <Provider><ProjectRoot /></Provider>; }
function ProjectRoot() {
  const {state,toast}=useApp();
  const [creating,setCreating]=useState(false);
  if(state.projects.length)return <Shell />;
  return <div className="boot-screen"><img src="/mark.svg" alt="" /><h2>还没有研究项目</h2><p>创建一个项目，开始整理文献与笔记。</p><button className="button primary" onClick={()=>setCreating(true)}><Plus size={16}/>创建新项目</button>{creating&&<NewProject onClose={()=>setCreating(false)}/ >}{toast&&<div className="toast" role="status">{toast}</div>}</div>;
}
function Shell() {
  const { state, project, page, setPage, updateState, toast, saveStatus } = useApp();
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
  function go(next: Page) { setPage(next); setMobileNav(false); }
  return <div className="app-shell"><a className="skip-link" href="#main">跳至主内容</a>{mobileNav && <button className="nav-backdrop" aria-label="关闭导航" onClick={() => setMobileNav(false)} />}<aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}><button className="brand" aria-label="ScholarNoteLM · 文献库" title="文献库" onClick={() => go('library')}><img src="/mark.svg" alt="" /><span>ScholarNote<span>LM</span></span></button><div className="workspace-label">当前研究项目</div><div className="project-switcher-wrap"><button className="project-switcher" title={project.name} aria-label={`切换项目：${project.name}`} aria-expanded={projectMenu} onClick={() => setProjectMenu(!projectMenu)}><span className={`project-avatar ${project.color}`}><Folder size={18} /></span><span><strong>{project.name}</strong><small>研究项目</small></span><ChevronDown size={14} /></button>{projectMenu && <><button className="menu-dismiss" aria-label="关闭项目菜单" onClick={() => setProjectMenu(false)} /><div className="project-menu"><div className="eyebrow">切换项目</div>{state.projects.map(p => <button key={p.id} onClick={() => { updateState(s => ({ ...s, active: p.id })); setProjectMenu(false); go('library'); }}><span className={`project-dot ${p.color}`} /><span>{p.name}</span>{p.id === project.id && <Check size={14} />}</button>)}<button className="project-create" onClick={() => { setProjectMenu(false); setNewProject(true); }}><Plus size={16} />创建新项目</button><button className="project-delete" onClick={()=>{setProjectMenu(false);setDeletingProject(true);}}><Trash2 size={16}/>删除当前项目</button></div></>}</div><button aria-label="搜索你的研究" title="搜索你的研究 · ⌘ K" className="sidebar-search" onClick={() => setGlobalSearch(true)}><Search size={15} /><span>搜索你的研究</span><kbd>⌘ K</kbd></button><div className="nav-label">工作区</div><nav className="main-nav" aria-label="主导航">{nav.map(item => <button key={item.id} aria-label={item.label} title={item.label} aria-current={page === item.id ? "page" : undefined} className={page === item.id ? 'active' : ''} onClick={() => go(item.id)}><item.icon size={18} strokeWidth={1.65} /><span>{item.label}</span>{item.id === 'library' && <small>{project.papers.length}</small>}{page === item.id && <i />}</button>)}</nav><div className="sidebar-bottom"><button aria-label="任务中心" title="任务中心" className={page === 'tasks' ? 'active' : ''} onClick={() => go('tasks')}><ListTodo size={17} /><span>任务中心</span>{running > 0 && <span className="task-count">{running}</span>}</button><button aria-label="设置" title="设置" className={page === 'settings' ? 'active' : ''} onClick={() => go('settings')}><Settings size={17} /><span>设置</span></button><div className="sidebar-profile"><span className="profile-avatar">研</span><div><strong>个人研究空间</strong><span>ScholarNoteLM · 0.6.0{import.meta.env.DEV ? ' · 开发版' : ''}</span></div><IconButton icon={CircleHelp} label="使用帮助" onClick={() => setHelp(true)} /></div></div></aside><div className="app-content"><header className="topbar"><div className="breadcrumbs"><button className="mobile-nav-toggle icon-button" aria-label="打开导航" onClick={() => setMobileNav(true)}><Menu size={18} /></button><Folder size={15} /><span>{project.name}</span><ChevronRight size={13} /><strong>{nav.find(n => n.id === page)?.label || (page === 'tasks' ? '任务中心' : '设置')}</strong></div><div className="topbar-right"><span className="save-state"><span className={`tiny-dot ${saveStatus === '保存失败' ? 'danger' : ''}`} />{saveStatus}</span><button className="prototype-badge" onClick={() => setHelp(true)}><span />研究工作台</button><IconButton icon={state.theme === 'light' ? Moon : Sun} label="切换主题" onClick={() => updateState(s => ({ ...s, theme: s.theme === 'light' ? 'dark' : 'light' }))} /></div></header><main ref={mainScroll} id="main" className={`main-content page-${page}`} key={`${project.id}-${page}`}>
    {page === 'search' && <SearchWorkbench />}{page === 'library' && <Library />}{page === 'chat' && <Chat />}{page === 'review' && <Review />}{page === 'reader' && <Reader />}{page === 'tasks' && <DownloadTasks />}{page === 'settings' && <ResearchSettings />}
  </main></div>{toast && <div className="toast" role="status"><Check size={17} />{toast}</div>}{deletingProject && <DeleteProject key={project.id} onClose={()=>setDeletingProject(false)}/ >}{newProject && <NewProject onClose={() => setNewProject(false)} />}{globalSearch && <GlobalSearch onClose={() => setGlobalSearch(false)} />}{help && <Modal title="欢迎来到 ScholarNoteLM" subtitle="研究工作台 · v0.6" onClose={() => setHelp(false)}><div className="help-content"><img src="/mark.svg" alt="" /><h3>把文献，变成有连接的知识。</h3><p>从 PubMed 检索或 Zotero 导入文献，整理全文、记录笔记，并基于项目文献进行问答和综述撰写。</p><div className="help-details"><span><Check size={16} />开始前，可在设置中连接模型服务。</span><span><Check size={16} />保存位置：设置 → 外观与存储，可查看项目工作目录。</span><span><Check size={16} />在文献库点击“一键更新文献”，准备问答和综述所需的材料。</span></div><button className="button primary" onClick={() => setHelp(false)}>开始探索 <ArrowRight size={15} /></button></div></Modal>}</div>;
}

function DeleteProject({onClose}:{onClose:()=>void}) {
  const {project,deleteProject,notify}=useApp();
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [projectPath,setProjectPath]=useState('');
  useEffect(()=>{let alive=true;void rpc<{projectPath:string}>('storage.status',{project:project.id}).then(v=>{if(alive)setProjectPath(v.projectPath);}).catch(e=>{if(alive)setError(message(e));});return()=>{alive=false;};},[project.id]);
  async function remove(){
    setBusy(true);setError('');
    try{await deleteProject(project.id);notify('项目及其文件已永久删除');onClose();}catch(e){setError(message(e));}finally{setBusy(false);}
  }
  return <Modal title="删除当前项目" subtitle={project.name} onClose={()=>{if(!busy)onClose();}}><form onSubmit={e=>{e.preventDefault();void remove();}}><p>项目内所有文件都将永久删除，包括文献、笔记、综述、已保存稿件和导出文件，无法恢复。</p><p className="quiet small">{projectPath || '正在读取项目路径…'}</p>{error&&<div className="wb-alert" role="alert">{error}</div>}<div className="modal-actions"><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button danger" disabled={busy||!projectPath}>{busy?'正在删除…':'确认删除项目'}</button></div></form></Modal>;
}

function NewProject({ onClose }: { onClose: () => void }) {
  const { updateState, setPage, notify } = useApp();
  const [name, setName] = useState(''); const [description, setDescription] = useState(''); const [folder,setFolder]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  async function create(){
    setBusy(true);setError('');
    try{const p:Project={id:crypto.randomUUID().replaceAll('-',''),name:name.trim(),description:description.trim(),color:'purple',papers:[],messages:[],sections:[{id:'intro',title:'引言',content:''}],notes:{},tasks:[]};
    await rpc('storage.register',{project:p.id,folder:folder.trim(),data:p});updateState(s=>({...s,active:p.id,projects:[...s.projects,p]}));setPage('library');notify('研究项目已创建');onClose();}catch(e){setError(message(e));}finally{setBusy(false);}
  }
  return <Modal title="开始一项新的研究" subtitle="一个项目，容纳你的文献、想法与发现。" onClose={()=>{if(!busy)onClose();}}><form onSubmit={e=>{e.preventDefault();void create();}}><label className="form-field">项目名称<input autoFocus required maxLength={60} placeholder="例如：神经炎症与认知功能" value={name} onChange={e=>setName(e.target.value)}/></label><label className="form-field">项目文件夹名<input required pattern="[A-Za-z0-9_㐀-䶿一-鿿]+" maxLength={64} placeholder="例如：神经炎症_2026" value={folder} onChange={e=>setFolder(e.target.value)}/><span>支持中文、英文、数字和下划线；在项目工作目录中创建同名文件夹。</span></label><label className="form-field">研究目标 <span>可选</span><textarea rows={3} placeholder="你想探索什么问题？" value={description} onChange={e=>setDescription(e.target.value)}/></label>{error&&<div className="wb-alert">{error}</div>}<div className="modal-actions"><span className="quiet small">文献与笔记将在项目间独立保存</span><button className="button primary" disabled={busy||!name.trim()||!folder.trim()}>{busy?'正在创建…':'创建项目'}<ArrowRight size={15}/></button></div></form></Modal>;
}

function GlobalSearch({ onClose }: { onClose: () => void }) {
  const { project, openPaper, setPage } = useApp(); const [value, setValue] = useState('');
  const results = project.papers.filter(p => `${p.title} ${p.id} ${p.author} ${p.tag}`.toLowerCase().includes(value.toLowerCase())).slice(0, 7);
  return <Modal title="搜索你的研究" subtitle={`当前项目 · ${project.name}`} onClose={onClose}><label className="search-field global-search-field"><Search size={18} /><input autoFocus aria-label="全局搜索" value={value} onChange={e => setValue(e.target.value)} placeholder="文献标题、PMID、作者…" /></label><div className="global-results">{results.map(p => <button key={p.id} onClick={() => { openPaper(p); onClose(); }}><FileText size={17} /><div><strong>{p.title}</strong><span>{p.journal} · {p.year} · 阅读与笔记</span></div><ArrowUpRight size={14} /></button>)}{!results.length && <Empty title="没有找到文献" text="试试其他关键词，或先向当前项目添加文献。" />}</div><div className="search-quick"><button onClick={() => { setPage('chat'); onClose(); }}><MessageSquare size={14} />文献问答</button><button onClick={() => { setPage('review'); onClose(); }}><SquarePen size={14} />综述工作台</button><kbd>ESC 关闭</kbd></div></Modal>;
}
