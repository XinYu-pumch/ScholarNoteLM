import {t as tr} from './i18n';
import {useEffect, useRef, useState} from 'react';
import {invoke, isTauri} from '@tauri-apps/api/core';
import {listen} from '@tauri-apps/api/event';
import {canNavigate} from './navigation';
import {Modal} from './ui';
import {message} from './research-api';
import {resolveCloseRequest} from './exitProtocol';

export function useNativeClose(flush: () => Promise<void>) {
  const current=useRef(flush); current.current=flush;
  const [saving,setSaving]=useState(false),[error,setError]=useState('');
  useEffect(()=>{
    if(!isTauri())return;
    let alive=true;
    const subscription=listen<number>('app-close-requested',event=>void resolveCloseRequest({
      canLeave:canNavigate,
      flush:()=>current.current(),
      saving:value=>{if(alive)setSaving(value);},
      error:e=>{if(alive)setError(tr("保存尚未完成，应用保持开启。{p0}",{p0:message(e)}));},
      answer:async allow=>{if(alive)await invoke('close_guard_answer',{ticket:event.payload,allow});},
    }));
    void subscription.then(async unlisten=>{
      if(!alive){unlisten();return;}
      await invoke('close_guard_ready',{ready:true});
    }).catch(e=>setError(tr("无法启用退出保护：{p0}",{p0:message(e)})));
    return()=>{alive=false;void subscription.then(unlisten=>unlisten()).catch(()=>{});};
  },[]);
  if(error)return <Modal title={tr("暂未退出应用")} onClose={()=>setError('')}><p role="alert">{tr(error)}</p><div className="modal-actions"><button data-dialog-autofocus className="button primary" onClick={()=>setError('')}>{tr("返回应用")}</button></div></Modal>;
  return saving?<Modal title={tr("正在保存本地修改")} onClose={()=>{}}><p role="status">{tr("保存完成后退出，请稍候。")}</p></Modal>:null;
}
