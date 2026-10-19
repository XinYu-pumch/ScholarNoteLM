import {t as tr} from './i18n';
import {configureLocale} from './i18n';
import {forgetPage} from './page-memory';
import {useNativeClose} from './useNativeClose';
import {flushLatestState} from './exitProtocol';
import {canNavigate, requestNavigation} from './navigation';
import {type Notice, type NoticeTone} from './Notification';
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import WorkspaceSetup, {type WorkspaceStartup} from './WorkspaceSetup';
import { emptyState, type AppState, type Page, type Project, type Paper } from './data';
import { readState, writeState, getWorkspaceWarnings } from './storage';
import {rpc,type WorkbenchData} from './research-api';

type Context = {
  state: AppState; project: Project; page: Page; setPage: (page: Page) => void;
  settingsTab: string; setSettingsTab: (tab: string) => void; openSettings: (tab: string) => void;
  updateProject: (update: (p: Project) => Project) => void;
  updateState: (update: (s: AppState) => AppState) => void;
  createProject: (project: Project, folder: string) => Promise<void>;
  retrySave: () => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  readerReturnPage: Page; openPaper: (paper: Paper) => void; paperId: string; setPaperId: (id: string) => void;
  notify: (message: string, options?: {tone?: NoticeTone; key?: string; scope?: string}) => void; toast: Notice | null; dismissToast: () => void; saveStatus: string;
};
const Context = createContext<Context | null>(null);
export function useApp() { const value = useContext(Context); if (!value) throw new Error('Missing app provider'); return value; }
export function Provider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(structuredClone(emptyState));
  const [loaded, setLoaded] = useState(false);
  const [workspaceStartup,setWorkspaceStartup]=useState<WorkspaceStartup>();
  const [loadError, setLoadError] = useState('');
  const [page, setPageRaw] = useState<Page>('library');
  const pageRef = useRef(page); pageRef.current = page;
  const setPage=(next:Page)=>{if(next!==pageRef.current)requestNavigation(()=>setPageRaw(next));};
  const [settingsTab,setSettingsTab]=useState('models');
  const [paperId, setPaperId] = useState('');
  const [readerReturnPage,setReaderReturnPage]=useState<Page>('library');
  useEffect(()=>{setPaperId('');},[state.active]);
  const [toast, setToast] = useState<Notice | null>(null);
  const notify = (message: string, options?: {tone?: NoticeTone; key?: string; scope?: string}) => { const tone=options?.tone||'info'; setToast(previous=>previous?.message===message&&previous.tone===tone&&previous.key===options?.key&&previous.scope===options?.scope?previous:{message,tone,key:options?.key,scope:options?.scope}); };
  const dismissToast=()=>setToast(null);
  useEffect(()=>{setToast(previous=>previous?.scope&&previous.scope!==state.active?null:previous);},[state.active]);
  const [persistedState, setPersistedState] = useState<AppState | null>(null);
  const [saveFailure, setSaveFailure] = useState(false);
  const saveStatus = persistedState === state ? '已保存到本地' : saveFailure ? '保存失败' : '正在保存…';
  const writeQueue = useRef(Promise.resolve());
  const saveRevision = useRef(0);
  const saveTimer = useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const flushing = useRef(false);
  const deleting = useRef(false);
  const latestState = useRef(state);
  latestState.current = state;
  const project = state.projects.find(p => p.id === state.active)!;
  useEffect(() => {
    let alive = true;
    configureLocale(navigator.language.toLowerCase().startsWith('zh')?'zh':'en');
    rpc<WorkspaceStartup>('storage.bootstrap').then(async info=>{
      if(info.state!=='ready'){if(alive)setWorkspaceStartup(info);return null;}
      return readState();
    }).then(value => { if (alive && value) { configureLocale(value.uiLanguage||'zh');setState(value); setLoaded(true); const warnings=getWorkspaceWarnings();if(warnings.length)notify('部分项目未能自动导入：\n'+warnings.join('\n'),{tone:'warning'}); } }).catch(error => { if (alive) setLoadError((error instanceof Error?error.message:String(error))+'。现有数据不会被覆盖；请检查安装环境后重试。'); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = state.theme;
    if (!loaded || flushing.current) return;
    const revision = ++saveRevision.current;
    const timer = setTimeout(() => {
      if (deleting.current) return;
      writeQueue.current = writeQueue.current.catch(() => {}).then(() => writeState(state)).then(() => { if (saveRevision.current === revision) { setPersistedState(state); setSaveFailure(false); } }).catch(() => { if (saveRevision.current === revision) { setSaveFailure(true); } });
    }, 300);
    saveTimer.current=timer;
    return () => clearTimeout(timer);
  }, [state, loaded]);
  useEffect(() => { if (!toast || toast.tone==='error' || toast.tone==='warning') return; const timer = setTimeout(() => setToast(null), 4200); return () => clearTimeout(timer); }, [toast]);
  useEffect(() => {
    if (!loaded || !state.active) return;
    let alive = true;
    const sync = () => { void rpc<WorkbenchData>('workspace', { project: state.active }).then(data => {
      if (!alive || deleting.current) return;
      setState(current => { const projects=current.projects.map(p => {
        if (p.id !== state.active) return p;
        const included = data.corpus.papers.filter(v => v.included);
        const retained = p.papers.filter(v => !v.researchManaged && !included.some(n => n.id === v.id));
        const history = [...(p.archivedPapers || []), ...p.papers.filter(v => v.researchManaged && !included.some(n => n.id === v.id))];
        const archivedPapers = history.filter((v,i) => history.findIndex(x => x.id === v.id) === i && !included.some(n => n.id === v.id));
        const papers = [...retained, ...included.map(v => {
          const previous = p.papers.find(x => x.id === v.id) || p.archivedPapers?.find(x => x.id === v.id);
          return { id:v.id, title:v.title, author:v.author, journal:v.journal, year:v.year, abstract:v.abstract, tag:'PubMed', status:previous?.status || 'abstract' as const, starred:previous?.starred || false, researchManaged:true, corpusSnapshot:data.corpus.snapshot };
        })];
        return JSON.stringify(papers) === JSON.stringify(p.papers) && JSON.stringify(archivedPapers) === JSON.stringify(p.archivedPapers || []) ? p : { ...p, papers, archivedPapers };
      }); return projects.every((p,i)=>p===current.projects[i])?current:{...current,projects}; });
    }).catch(() => {}); };
    sync(); window.addEventListener('research-changed',sync);
    return () => { alive=false; window.removeEventListener('research-changed',sync); };
  }, [loaded,state.active]);
  const retrySave = async () => {
    clearTimeout(saveTimer.current); ++saveRevision.current;
    flushing.current=true;
    try {const snapshot=await flushLatestState(writeQueue.current,()=>latestState.current,writeState);setPersistedState(snapshot);setSaveFailure(false);}
    catch(e){setSaveFailure(true);throw e;}finally{flushing.current=false;}
  };
  const createProject = async (project: Project, folder: string) => {
    clearTimeout(saveTimer.current); ++saveRevision.current; flushing.current=true;
    try {
      await writeQueue.current.catch(()=>{});
      await rpc('storage.register',{project:project.id,folder,data:project});
      const next={...latestState.current,active:project.id,projects:[...latestState.current.projects.filter(p=>p.id!==project.id),project]};
      await writeState(next);latestState.current=next;setState(next);setPersistedState(next);setSaveFailure(false);setPageRaw('library');
    } finally {flushing.current=false;}
  };
  const deleteProject = async (id: string) => {
    if (deleting.current) throw new Error('项目删除正在进行');
    if (!await canNavigate()) throw new Error('请先保存或取消当前编辑，再删除项目');
    deleting.current = true;
    ++saveRevision.current;
    try {
      await writeQueue.current.catch(() => {});
      await writeState(latestState.current);
      const result = await rpc<{state:AppState;deleted:boolean}>('storage.delete',{project:id,confirm:id});
      forgetPage(id);setState(result.state);setPersistedState(result.state);setSaveFailure(false);
      setPageRaw('library');setPaperId('');

    } finally { deleting.current = false; }
  };
  const closeDialog=useNativeClose(async()=>{
    if(!loaded)return;
    if(deleting.current)throw new Error('项目删除正在进行，请稍后再退出。');
    flushing.current=true;
    clearTimeout(saveTimer.current);
    ++saveRevision.current;
    try {
      const snapshot=await flushLatestState(writeQueue.current,()=>latestState.current,writeState);
      setPersistedState(snapshot);setSaveFailure(false);
    } catch(e) {setSaveFailure(true);throw e;}
    finally {flushing.current=false;}
  });
  if (workspaceStartup) return <WorkspaceSetup status={workspaceStartup} onReady={()=>location.reload()}/>;
  if (!loaded) return <div className="boot-screen"><img src="/mark.svg" alt="" /><h2>ScholarNoteLM</h2><p>{tr(loadError)||tr("正在打开你的研究空间…")}</p>{loadError && <button className="button" onClick={() => location.reload()}>{tr("重新加载")}</button>}</div>;
  const updateProject = (fn: (p: Project) => Project) => setState(current => ({ ...current, projects: current.projects.map(p => p.id === state.active ? fn(p) : p) }));
  return <Context.Provider value={{ state, project, page, setPage, createProject, retrySave, deleteProject, settingsTab,setSettingsTab,openSettings:tab=>requestNavigation(()=>{setSettingsTab(tab);setPageRaw('settings');}),updateProject, updateState: fn=>{const next=fn(latestState.current);if(next.active===latestState.current.active){configureLocale(next.uiLanguage||'zh');setState(fn);}else requestNavigation(()=>{setState(fn);setPageRaw('library');});}, paperId, setPaperId, readerReturnPage, openPaper: paper => requestNavigation(() => { if(pageRef.current!=='reader')setReaderReturnPage(pageRef.current); setPaperId(paper.id); setPageRaw('reader'); }), notify, toast, dismissToast, saveStatus }}>{children}{closeDialog}</Context.Provider>;
}
