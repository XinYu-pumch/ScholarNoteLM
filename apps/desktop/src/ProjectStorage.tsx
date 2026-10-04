import {useEffect,useState} from 'react';
import {FolderOpen,Folder,HardDrive,Package,Trash2,LoaderCircle} from 'lucide-react';
import {useApp} from './context';
import {rpc,message,changed} from './research-api';
import {downloadChanged} from './download-api';
import {Modal} from './ui';
import './project-storage.css';

type StorageInfo={workspace:string;system:string;projectPath:string;folder:string;folders:Record<string,string>};
export function StorageSettings(){
 const {project,notify}=useApp();const [data,setData]=useState<StorageInfo>();const [path,setPath]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const load=async()=>{const d=await rpc<StorageInfo>('storage.status',{project:project.id});setData(d);setPath(d.workspace);};
 useEffect(()=>{void load().catch(e=>setError(message(e)));},[project.id]);
 async function run(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();}catch(e){setError(message(e));}finally{setBusy(false);}}
 return <section className="project-storage"><h3>项目保存位置</h3><p className="quiet small">更换位置时，所有项目文件会一起迁移。</p>{error&&<div role="alert" className="wb-alert">{error}</div>}<div className="storage-location"><label className="form-field">保存位置<input aria-label="项目保存位置" value={path} onChange={e=>setPath(e.target.value)} placeholder="选择文件夹或输入绝对路径"/></label><button className="button secondary" disabled={busy} onClick={()=>void run(async()=>{const r=await rpc<{path:string}>('storage.choose');if(r.path)setPath(r.path);})}><FolderOpen size={15}/>选择文件夹</button></div><div className="download-actions"><button className="button primary" disabled={busy||!path.trim()||path===data?.workspace} onClick={()=>void run(async()=>{await rpc('storage.move',{path:path.trim()});await load();changed();downloadChanged();notify('项目文件已迁移，工作目录已更新');})}>{busy?<LoaderCircle className="spin" size={15}/>:<HardDrive size={15}/>}更换位置并迁移</button><button className="text-button" disabled={!data||busy} onClick={()=>void run(async()=>{await rpc('storage.open',{project:project.id});})}><FolderOpen size={15}/>打开项目文件夹</button></div>{data&&<><p className="quiet small storage-path">当前项目：{data.projectPath}</p><details className="storage-file-help"><summary>文件说明</summary><div className="storage-tree"><div><Folder size={16}/><strong>{data.folder}/</strong><span>当前项目</span></div>{['pubmed','pdf','abstracts','logs','markdown','vectors','summaries','notes','qa','review','reviews','packages','metadata'].map(name=>{const description=data.folders[name];return <div key={name}><code>{name}/</code><span>{description}</span></div>;})}</div><p className="quiet small storage-path">项目位置：{data.projectPath}</p><div className="storage-system"><HardDrive size={18}/><div><strong>系统资源保留在应用内部</strong><p>JCR、MeSH、Sci-Hub Bloom、本地模型、运行时和服务配置由应用统一管理。</p><code>{data.system}</code></div></div></details></>}</section>;
}

export function ProjectFilesActions({disabled=false}:{disabled?:boolean}){
 const {project,notify}=useApp();const [busy,setBusy]=useState(false);
 async function pack(){setBusy(true);try{const r=await rpc<{path:string;pdf:number;abstracts:number}>('download.export',{project:project.id});notify(`已打包 ${r.pdf} 篇 PDF、${r.abstracts} 份摘要：${r.path}`);}catch(e){notify(message(e));}finally{setBusy(false);}}
 return <div className="project-file-tools"><button className="text-button" onClick={()=>void rpc('storage.open',{project:project.id}).catch(e=>notify(message(e)))}><FolderOpen size={14}/>打开项目文件夹</button><button className="text-button" disabled={disabled||busy} onClick={()=>void pack()}><Package size={14}/>{busy?'正在打包…':'打包当前文献'}</button></div>;
}
