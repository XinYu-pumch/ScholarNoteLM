import {t as tr} from './i18n';
import Field from './Field';
import {useUnsavedChanges} from './useUnsavedChanges';
import {useEffect,useState} from 'react';
import {FolderOpen,Folder,HardDrive,Package,LoaderCircle} from 'lucide-react';
import {useApp} from './context';
import {rpc,message,changed} from './research-api';
import {downloadChanged} from './download-api';

import './project-storage.css';

type StorageInfo={workspace:string;system:string;projectPath:string;folder:string;folders:Record<string,string>};
export function StorageSettings(){
 const {project,notify}=useApp();const [data,setData]=useState<StorageInfo>();const [path,setPath]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const load=async()=>{const d=await rpc<StorageInfo>('storage.status',{project:project.id});setData(d);setPath(d.workspace);};
 useEffect(()=>{void load().catch(e=>setError(message(e)));},[project.id]);
 async function run(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();}catch(e){setError(message(e));}finally{setBusy(false);}}
 async function migrate(){if(!path.trim())throw new Error('请选择项目保存位置');await rpc('storage.move',{path:path.trim()});await load();changed();downloadChanged();notify('项目文件已迁移，工作目录已更新',{tone:'success'});}
 const draftDialog=useUnsavedChanges({label:'项目保存位置（保存会迁移所有项目文件）',saveLabel:'迁移并离开',dirty:!!data&&path!==data.workspace,busy,save:migrate,discard:()=>setPath(data?.workspace||'')});
 return <section className="project-storage">{draftDialog}<h3>{tr("项目保存位置")}</h3><p className="quiet small">{tr("更换位置时，所有项目文件会一起迁移。")}</p>{error&&<div role="alert" className="wb-alert">{tr(error)}</div>}<div className="storage-location"><Field className="form-field">{tr("保存位置")}<input aria-label={tr("项目保存位置")} disabled={busy} value={path} onChange={e=>setPath(e.target.value)} placeholder={tr("选择文件夹或输入绝对路径")}/></Field><button className="button secondary" disabled={busy} onClick={()=>void run(async()=>{const r=await rpc<{path:string}>('storage.choose');if(r.path)setPath(r.path);})}><FolderOpen size={15}/>{tr("选择文件夹")}</button></div><div className="download-actions"><button className="button primary" disabled={busy||!path.trim()||path===data?.workspace} onClick={()=>void run(migrate)}>{busy?<LoaderCircle className="spin" size={15}/>:<HardDrive size={15}/>}{tr("更换位置并迁移")}</button><button className="text-button" disabled={!data||busy} onClick={()=>void run(async()=>{await rpc('storage.open',{project:project.id});})}><FolderOpen size={15}/>{tr("打开项目文件夹")}</button></div>{data&&<><p className="quiet small storage-path">{tr("当前项目：")}{data.projectPath}</p><details className="storage-file-help"><summary>{tr("文件说明")}</summary><div className="storage-tree"><div><Folder size={16}/><strong>{data.folder}/</strong><span>{tr("当前项目")}</span></div>{['pubmed','pdf','abstracts','logs','markdown','vectors','summaries','notes','qa','review','reviews','packages','metadata'].map(name=>{const description=data.folders[name];return <div key={name}><code>{name}/</code><span>{description}</span></div>;})}</div><p className="quiet small storage-path">{tr("项目位置：")}{data.projectPath}</p><div className="storage-system"><HardDrive size={18}/><div><strong>{tr("系统资源保留在应用内部")}</strong><p>{tr("JCR、MeSH、Sci-Hub Bloom、本地模型、运行时和服务配置由应用统一管理。")}</p><code>{data.system}</code></div></div></details></>}</section>;
}

export function ProjectFilesActions({disabled=false}:{disabled?:boolean}){
 const {project,notify}=useApp();const [busy,setBusy]=useState(false);
 async function pack(){setBusy(true);try{const r=await rpc<{path:string;pdf:number;abstracts:number}>('download.export',{project:project.id});notify(tr("已打包 {p0} 篇 PDF、{p1} 份摘要：{p2}",{p0:r.pdf,p1:r.abstracts,p2:r.path}));}catch(e){notify(message(e),{tone:'error'});}finally{setBusy(false);}}
 return <div className="project-file-tools"><button className="text-button" onClick={()=>void rpc('storage.open',{project:project.id}).catch(e=>notify(message(e),{tone:'error'}))}><FolderOpen size={14}/>{tr("打开项目文件夹")}</button><button className="text-button" disabled={disabled||busy} onClick={()=>void pack()}><Package size={14}/>{busy?tr("正在打包…"):tr("打包当前文献")}</button></div>;
}
