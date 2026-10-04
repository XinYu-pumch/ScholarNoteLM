import {useState} from 'react';
import {Modal} from './ui';
import {message} from './research-api';
export default function ConversationDialog({mode,name,count=1,onClose,onSubmit}:{count?:number;mode:'rename'|'delete';name:string;onClose:()=>void;onSubmit:(name:string)=>Promise<void>}){
 const [title,setTitle]=useState(name),[busy,setBusy]=useState(false),[error,setError]=useState('');
 return <Modal title={mode==='rename'?'重命名对话':count>1?`删除 ${count} 个对话`:'删除对话'} onClose={()=>{if(!busy)onClose();}}><form className="wb-form" onSubmit={async e=>{e.preventDefault();setBusy(true);try{await onSubmit(title.trim());onClose();}catch(e){setError(message(e));}finally{setBusy(false);}}}>
 {mode==='rename'?<label>对话名称<input aria-label="新的对话名称" autoFocus required maxLength={80} value={title} disabled={busy} onChange={e=>setTitle(e.target.value)}/></label>:<p>{count>1?`删除所选的 ${count} 个对话？`:`删除“${name}”？`}其他对话、已建立的分支及其证据会保留。</p>}
 {error&&<p role="alert" className="wb-alert">{error}</p>}<div className="dialog-actions"><button type="button" className="button secondary" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy||mode==='rename'&&!title.trim()}>{busy?'正在处理…':mode==='rename'?'保存名称':'删除对话'}</button></div></form></Modal>;
}
