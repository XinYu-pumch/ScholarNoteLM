import NumberInput from './NumberInput';
import {useEffect,useState} from 'react';
import {FileText,FolderOpen,Save,LoaderCircle,Check,ChevronRight,Pencil,RotateCcw} from 'lucide-react';
import {useApp} from './context';
import {rpc,message,stamp} from './research-api';
import {downloadChanged,recoveryLabel,mb,type DownloadConfig,type PdfAsset,type DownloadItem} from './download-api';
import './downloads.css';

export function PdfStatus({asset,item}:{asset?:PdfAsset;item?:DownloadItem}){
 const active=item&&['running','queued','paused'].includes(item.state);
 return <span className={`pdf-status ${asset?.exists?'ready':active?'working':item?.state==='failed'?'failed':''}`} title={item?.error||asset?.source}>{asset?.exists?<><Check size={12}/>已有 PDF</>:active?<>{item.state==='running'&&<LoaderCircle size={12} className="spin"/>}{recoveryLabel(item)}</>:item?.state==='deferred'?'未完成，可重试':item?.state==='failed'?'未获取全文':'待下载'}</span>;
}
export function pdfIdentityLabel(identity:PdfAsset['identity']):string{
 if(typeof identity==='string')return identity;
 if(!identity||typeof identity!=='object')return '';
 const reasons:Record<string,string>={doi_in_frontmatter:'正文 DOI 与目标文献一致',title_in_frontmatter:'正文标题与目标文献一致',conflicting_content:'正文身份与目标文献不符',insufficient_text:'可提取文字不足，正文身份待核验',insufficient_identity_evidence:'正文身份信息不足，待核验',text_extraction_failed:'正文文字提取失败，身份待核验',invalid_pdf:'PDF 文件校验未通过',identity_timeout:'正文身份校验超时',staging_changed:'文件发生变化，身份待核验'};
 const reason=typeof identity.reason==='string'?reasons[identity.reason]:undefined;
 if(typeof reason==='string')return reason;
 const status=({match:'正文身份校验通过',mismatch:'正文身份不匹配',unverifiable:'正文身份待核验'} as Record<string,string>)[identity.status||''];
 return typeof status==='string'?status:'正文身份校验结果已记录';
}
export function PdfDetails({pmid,asset,item}:{pmid:string;asset?:PdfAsset;item?:DownloadItem}){
 const {project,notify,setPage}=useApp();const [busy,setBusy]=useState(false);
 async function act(fn:()=>Promise<unknown>){setBusy(true);try{await fn();downloadChanged();}catch(e){notify(message(e),{tone:'error'});}finally{setBusy(false);}}
 return <section className="pdf-details"><div className="section-heading"><h3>PDF 全文</h3><PdfStatus asset={asset} item={item}/></div>{asset?.exists?<><div className="pdf-facts"><span>来源 <b>{asset.source}</b></span><span>文件 <b>{mb(asset.bytes)} · {asset.pages} 页</b></span>{asset.version!==undefined&&<span>版本 <b>{asset.version}{asset.isManuscript?' · 作者手稿':''}</b></span>}<span>下载时间 <b>{stamp(asset.downloaded)}</b></span></div><p className="quiet small">{asset.selectionReason||pdfIdentityLabel(asset.identity)}</p><code className="pdf-path">{asset.path}</code><div className="download-actions"><button className="button primary compact" disabled={busy} onClick={()=>void act(()=>rpc('download.open',{project:project.id,pmid}))}><FileText size={14}/>打开 PDF</button><button className="button secondary compact" disabled={busy} onClick={()=>void act(()=>rpc('download.open',{project:project.id,pmid,folder:true}))}><FolderOpen size={14}/>所在文件夹</button></div></>:<p className="quiet small">{item?.error||'下载成功后，可在此打开 PDF。'}</p>}<div className="download-actions"><button className="text-button" onClick={()=>setPage('search')}>从 Zotero 导入文献及 PDF</button><button className="text-button" onClick={()=>setPage('tasks')}>查看任务与报告</button></div></section>;
}
export {default} from './TaskCenter';
const DEFAULT_MIRRORS=['https://sci-hub.ru','https://sci-hub.su','https://sci-hub.st','https://sci-hub.red','https://sci-hub.box'];
export function DownloadSettings(){
 const {notify}=useApp();const [cfg,setCfg]=useState<DownloadConfig|null>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [saved,setSaved]=useState('');const [mirrors,setMirrors]=useState('');const [editingMirrors,setEditingMirrors]=useState(false);
 useEffect(()=>{void rpc<DownloadConfig>('download.settings').then(v=>{setCfg(v);setMirrors(v.mirrors.join('\n'));}).catch(e=>setError(message(e)));},[]);
 if(!cfg)return <p className="quiet">{error||'正在读取下载配置…'}</p>;
 const set=(patch:Partial<DownloadConfig>)=>{setSaved('');setCfg(v=>v?{...v,...patch}:v);};
 async function save(){if(!cfg||editingMirrors)return;setBusy(true);setError('');setSaved('');try{const value=await rpc<DownloadConfig>('download.settings.save',cfg);setCfg(value);setSaved('下载设置已保存');}catch(e){setError(message(e));}finally{setBusy(false);}}
 async function saveMirrors(){setBusy(true);setError('');setSaved('');try{const value=await rpc<DownloadConfig>('download.settings.save',{mirrors:mirrors.split('\n').map(v=>v.trim()).filter(Boolean)});setCfg(v=>v?{...v,mirrors:value.mirrors}:v);setMirrors(value.mirrors.join('\n'));setEditingMirrors(false);notify('Sci-Hub 镜像已保存');}catch(e){setError(message(e));}finally{setBusy(false);}}
 return <div className="download-settings"><h2>PDF 下载</h2><p className="quiet">管理全文来源和下载速度。</p>
 {error&&<div className="wb-alert" role="alert">{error}</div>}{saved&&<div className="wb-success" role="status"><Check size={15}/>{saved}</div>}
 <form onSubmit={e=>{e.preventDefault();void save();}}><fieldset disabled={busy} className="pdf-settings-fields">
  <div className="pdf-source-grid">
   <section className="pdf-source-card pdf-connection-card wb-form"><h3>开放获取</h3><label className="wb-check"><input type="checkbox" checked={cfg.fastOa} onChange={e=>set({fastOa:e.target.checked})}/>从开放获取来源下载</label><label className="pdf-connection-field">Unpaywall 联系邮箱<input aria-label="Unpaywall 联系邮箱" type="email" value={cfg.email} placeholder="research@example.com" onChange={e=>set({email:e.target.value})}/></label><p className="quiet small">无需注册；留空时跳过 Unpaywall。</p></section>
   <section className="pdf-source-card pdf-connection-card wb-form"><h3>Zotero</h3><label className="pdf-connection-field">本地地址<input aria-label="Zotero 本地地址" value={cfg.zoteroAddress??'localhost:23119'} placeholder="localhost:23119" onChange={e=>set({zoteroAddress:e.target.value})}/></label><p className="quiet small">补充 Zotero 中已有的 PDF。需打开 Zotero 并启用本地 API；留空则跳过。</p></section>
   <details className="pdf-source-card pdf-mirrors"><summary><ChevronRight size={15}/><span>Sci-Hub 镜像</span></summary><div className="pdf-mirrors-body wb-form"><div className="pdf-mirror-actions"><button type="button" className="button secondary compact" onClick={()=>{setMirrors(DEFAULT_MIRRORS.join('\n'));setEditingMirrors(true);setSaved('');}}><RotateCcw size={14}/>恢复默认</button>{editingMirrors?<><button type="button" className="button secondary compact" onClick={()=>{setMirrors(cfg.mirrors.join('\n'));setEditingMirrors(false);setError('');}}>取消</button><button type="button" className="button primary compact" onClick={()=>void saveMirrors()}><Save size={14}/>保存</button></>:<button type="button" className="button secondary compact" onClick={()=>{setEditingMirrors(true);setSaved('');}}><Pencil size={14}/>编辑</button>}</div><label>镜像地址 · 每行一个<textarea aria-label="Sci-Hub 镜像地址" rows={5} value={mirrors} readOnly={!editingMirrors} onChange={e=>{setMirrors(e.target.value);setSaved('');}} spellCheck={false}/></label><p className="quiet small">{editingMirrors?'点击保存后生效；清空后停用。':'无法连接的镜像会自动跳过。'}</p></div></details>
  </div>
  <details className="model-advanced pdf-request-settings"><summary><ChevronRight size={14}/>下载速度与超时</summary><div className="pdf-request-grid">
   {([['unpaywallConcurrency','Unpaywall 并发',1,30],['pmcConcurrency','PMC 并发',1,10],['europePmcConcurrency','Europe PMC 并发',1,4],['timeout','请求超时 · 秒',5,180],['europePmcTimeout','Europe PMC 超时 · 秒',5,300],['europePmcAttempts','Europe PMC 尝试次数',1,3],['attempts','PMC 尝试次数',1,5],['oaFileTimeout','单文件下载超时 · 秒',5,300],['oaArticleTimeout','单篇查找超时 · 秒',5,600],['s3ArticleTimeout','PMC 单篇超时 · 秒',5,300]] as const).map(([key,label,min,max])=><label key={key}>{label}<NumberInput aria-label={label} type="number" min={min} max={max} value={cfg[key]} onChange={e=>set({[key]:Number(e.target.value)})}/></label>)}
  </div></details>
 </fieldset><div className="model-save-bar"><span>用于之后的下载和重试</span><button className="button primary" disabled={busy||editingMirrors}><Save size={15}/>{busy?'正在保存…':'保存下载设置'}</button></div></form></div>;
}
