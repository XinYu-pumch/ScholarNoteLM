import {useState} from 'react';
import {FolderOpen,ArrowRight,LoaderCircle} from 'lucide-react';
import Field from './Field';
import {rpc,message} from './research-api';
import {t as tr} from './i18n';

export type WorkspaceStartup={state:'required'|'unavailable'|'ready';workspace:string};
export default function WorkspaceSetup({status,onReady}:{status:WorkspaceStartup;onReady:()=>void}){
 const [path,setPath]=useState(status.workspace);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 async function run(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(e){setError(message(e));}finally{setBusy(false);}}
 const unavailable=status.state==='unavailable';
 return <main className="boot-screen"><section className="workspace-setup"><img src="/mark.svg" alt=""/><h1>{tr(unavailable?'连接研究工作目录':'选择研究工作目录')}</h1><p>{tr(unavailable?'原工作目录暂时不可访问。请连接原磁盘后重试，或选择移动后的完整工作目录。':'选择保存论文、笔记和综述的文件夹。你可以使用本机或外置磁盘上的绝对路径。')}</p>
 <form onSubmit={e=>{e.preventDefault();void run(async()=>{await rpc('storage.select',{path:path.trim()});onReady();});}}>
 <Field className="form-field">{tr('工作目录')}<input autoFocus required aria-label={tr('工作目录')} value={path} disabled={busy} onChange={e=>{setPath(e.target.value);setError('');}} placeholder="/Users/yourname/Documents/ScholarNoteLM"/></Field>
 <div className="workspace-setup-actions"><button type="button" className="button secondary" disabled={busy} onClick={()=>void run(async()=>{const result=await rpc<{path:string}>('storage.choose');if(result.path)setPath(result.path);})}><FolderOpen size={16}/>{tr('选择文件夹')}</button>{unavailable&&<button type="button" className="button secondary" disabled={busy} onClick={()=>void run(async()=>{const result=await rpc<WorkspaceStartup>('storage.bootstrap');if(result.state==='ready')onReady();else throw new Error('原工作目录仍不可访问');})}>{tr('重试')}</button>}<button className="button primary" disabled={busy||!path.trim()}>{busy?<LoaderCircle size={16} className="spin"/>:<ArrowRight size={16}/>} {tr(unavailable?'连接目录':'使用此目录')}</button></div>
 {error&&<div className="wb-alert" role="alert">{tr(error)}</div>}</form><p className="quiet small">{tr('已有文件不会被覆盖。之后可在设置中更换工作目录。')}</p></section></main>;
}
