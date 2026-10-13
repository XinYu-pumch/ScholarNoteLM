import {useState} from 'react';
import DraftModal,{DraftCancel} from './DraftModal';
import {message} from './research-api';
export default function ConversationDialog({mode,name,count=1,onClose,onSubmit}:{count?:number;mode:'rename'|'delete';name:string;onClose:()=>void;onSubmit:(name:string)=>Promise<void>}){
 const [title,setTitle]=useState(name),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function persist(){if(mode==='rename'&&!title.trim())throw new Error('请输入对话名称');await onSubmit(title.trim());onClose();}
 return <DraftModal dirty={mode==='rename'&&title!==name} busy={busy} save={persist} title={mode==='rename'?'重命名对话':count>1?`删除 ${count} 个对话`:'删除对话'} onClose={onClose}><form className="wb-form" onSubmit={async e=>{e.preventDefault();setBusy(true);try{await persist();}catch(e){setError(message(e));}finally{setBusy(false);}}}>
 {mode==='rename'?<label>对话名称<input aria-label="新的对话名称" autoFocus required maxLength={80} value={title} disabled={busy} onChange={e=>setTitle(e.target.value)}/></label>:<p>{count>1?`删除所选的 ${count} 个对话？`:`删除“${name}”？`}删除后无法恢复。其他对话、已建立的分支及其证据会保留。</p>}
 {error&&<p role="alert" className="wb-alert">{error}</p>}<div className="dialog-actions"><DraftCancel data-dialog-autofocus={mode==='delete'||undefined} className="button secondary" disabled={busy}>取消</DraftCancel><button className={`button primary ${mode==='delete'?'danger':''}`} disabled={busy||mode==='rename'&&!title.trim()}>{busy?'正在处理…':mode==='rename'?'保存名称':'删除对话'}</button></div></form></DraftModal>;
}
