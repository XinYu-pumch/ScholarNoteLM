import {t as tr} from './i18n';
import {useUnsavedChanges} from './useUnsavedChanges';
import {useEffect,useRef,useState} from 'react';
import {Save} from 'lucide-react';
import {useApp} from './context';
import {rpc,message} from './research-api';
import {downloadChanged} from './download-api';
import Select from './Select';

import {probeCompute,type ComputeDevice,type MarkdownSettingsData as Settings} from './markdown-api';

export function MarkdownSettings(){
 const {project,notify}=useApp();const [data,setData]=useState<Settings|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const baseline=useRef<Settings|null>(null);
 const [compute,setCompute]=useState<ComputeDevice|null>(null);
 useEffect(()=>{let live=true;void probeCompute().then(v=>{if(live)setCompute(v);}).catch(()=>{});return()=>{live=false;};},[]);
 useEffect(()=>{let live=true;setData(null);void rpc<Settings>('markdown.settings',{project:project.id}).then(d=>{if(live){setData(d);baseline.current=d;}}).catch(e=>{if(live)setError(message(e));});return()=>{live=false;};},[project.id]);
 async function persist(){if(!data)return;const saved=await rpc<Settings>('markdown.settings.save',{project:project.id,...data.config});setData(saved);baseline.current=saved;setError('');downloadChanged();notify('转换设置已保存',{tone:'success'});}
 async function save(){setBusy(true);try{await persist();}catch(e){setError(message(e));}finally{setBusy(false);}}
 const draftDialog=useUnsavedChanges({label:'全文转换设置',dirty:!!baseline.current&&JSON.stringify(data?.config)!==JSON.stringify(baseline.current.config),busy,save:persist,discard:()=>setData(baseline.current)});
 const cfg=data?.config;
 function change(patch:Partial<Settings['config']>){setData(d=>d?{...d,config:{...d.config,...patch}}:d);}
 return <div className="download-settings">{draftDialog}<h2>{tr("全文转换")}</h2><div className="settings-feedback">{error&&<div className="wb-alert" role="alert">{tr(error)}</div>}</div>{!data&&!error&&<p className="quiet">{tr("正在读取转换设置…")}</p>}{data&&cfg&&<>
 {!data.ready&&<div className="wb-alert" role="alert">{tr("转换环境尚未就绪")}{data.missing.length?tr("：缺少 {p0}",{p0:data.missing.join('、')}):''}</div>}
 <div className="conversion-settings wb-form"><label>{tr("计算设备")}<Select aria-label={tr("计算设备")} disabled={busy} value={cfg.device} onChange={e=>change({device:e.target.value})}><option value="auto">{tr("自动选择")}</option><option value="cpu">CPU</option><option value="mps">Apple Silicon</option><option value="cuda">NVIDIA GPU</option></Select></label><label>{tr("文字提取进程")}<Select aria-label={tr("文字提取进程")} disabled={busy} value={String(cfg.pdftextWorkers)} onChange={e=>change({pdftextWorkers:e.target.value==='auto'?'auto':Number(e.target.value)})}><option value="auto">{tr("自动")}</option>{[1,2,4,8,16].map(n=><option key={n} value={n}>{n}</option>)}</Select></label></div>
 <p className="quiet" role="status">{compute?tr("自动检测：{p0}",{p0:compute.name}):tr("正在检测计算设备…")}{compute?.reason&&<> · {tr(compute.reason)}</>}{cfg.device!=='auto'&&<> · {tr("已手动选择设备，转换时验证可用性")}</>}</p>
 <div className="model-save-bar"><button className="button primary" disabled={busy} onClick={()=>void save()}><Save size={15}/>{tr("保存设置")}</button></div></>}</div>;
}
