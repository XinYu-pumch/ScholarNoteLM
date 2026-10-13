import {t as tr} from './i18n';
import {useEffect, useRef, useState} from 'react';
import {Modal} from './ui';
import {message} from './research-api';
import {registerNavigationGuard} from './navigation';

export function useDraftGuard(options: {
  label: string;
  dirty: boolean;
  busy: boolean;
  save: () => Promise<void>;
  discard: () => void;
  saveLabel?: string;
  scope?: 'page' | 'dialog';
}) {
  const current = useRef(options);
  current.current = options;
  const resolve = useRef<((allowed: boolean) => void) | null>(null);
  const savingRef = useRef(false);
  const mounted = useRef(true);
  const continueButton = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(()=>{if(error&&!saving)continueButton.current?.focus();},[error,saving]);
  const check = () => {
    if (current.current.busy || savingRef.current) return false;
    if (!current.current.dirty) return true;
    if (resolve.current) return false;
    setError(''); setOpen(true);
    return new Promise<boolean>(done => { resolve.current = done; });
  };
  useEffect(() => {
    mounted.current=true;
    const unregister = registerNavigationGuard(check,options.scope==='dialog'?1:0);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (current.current.dirty || savingRef.current) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => { mounted.current=false; unregister(); if(!savingRef.current){resolve.current?.(false); resolve.current = null;} window.removeEventListener('beforeunload', beforeUnload); };
  }, []);
  function finish(allowed: boolean) {
    if (savingRef.current) return;
    const done=resolve.current;resolve.current=null;
    if(mounted.current)setOpen(false);done?.(allowed);
  }
  async function saveAndLeave() {
    if (savingRef.current) return;
    savingRef.current = true; setSaving(true); setError('');
    try {
      await current.current.save();
      savingRef.current = false; finish(true);
    } catch (e) { if(mounted.current)setError(message(e));else {resolve.current?.(false);resolve.current=null;} }
    finally { savingRef.current = false; if(mounted.current)setSaving(false); }
  }
  const dialog = open ? <Modal title={tr("保存修改后离开？")} subtitle={tr("{p0}有未保存的修改。",{p0:options.label})} onClose={() => finish(false)}>
    <p>{tr("保存成功后将继续刚才的操作；不保存会放弃本次修改。")}</p>
    {error && <p className="wb-inline-error" role="alert">{tr(error)}</p>}
    <div className="modal-actions draft-actions">
      <button ref={continueButton} data-dialog-autofocus className="button secondary" disabled={saving} onClick={() => finish(false)}>{tr("继续编辑")}</button>
      <button className="button secondary danger" disabled={saving} onClick={() => { finish(true); current.current.discard(); }}>{tr("不保存并离开")}</button>
      <button className="button primary" disabled={saving} onClick={() => void saveAndLeave()}>{saving?tr("正在保存…"):options.saveLabel||tr("保存并离开")}</button>
    </div>
  </Modal> : null;
  return {dialog, leave: (action: () => void) => { void Promise.resolve(check()).then(allowed => { if(allowed)action(); }); }};
}
export function useUnsavedChanges(options: Parameters<typeof useDraftGuard>[0]) { return useDraftGuard(options).dialog; }
