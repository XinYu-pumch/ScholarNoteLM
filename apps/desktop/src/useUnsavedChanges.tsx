import {useEffect, useRef, useState} from 'react';
import {Modal} from './ui';
import {message} from './research-api';
import {registerNavigationGuard} from './navigation';

export function useUnsavedChanges(options: {
  label: string;
  dirty: boolean;
  busy: boolean;
  save: () => Promise<void>;
  discard: () => void;
}) {
  const current = useRef(options);
  current.current = options;
  const resolve = useRef<((allowed: boolean) => void) | null>(null);
  const savingRef = useRef(false);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const unregister = registerNavigationGuard(() => {
      if (current.current.busy || savingRef.current) return false;
      if (!current.current.dirty) return true;
      setError(''); setOpen(true);
      return new Promise<boolean>(done => { resolve.current = done; });
    });
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (current.current.dirty || savingRef.current) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => { unregister(); resolve.current?.(false); resolve.current = null; window.removeEventListener('beforeunload', beforeUnload); };
  }, []);
  function finish(allowed: boolean) {
    if (savingRef.current) return;
    setOpen(false); resolve.current?.(allowed); resolve.current = null;
  }
  async function saveAndLeave() {
    if (savingRef.current) return;
    savingRef.current = true; setSaving(true); setError('');
    try {
      await current.current.save();
      savingRef.current = false; finish(true);
    } catch (e) { setError(message(e)); }
    finally { savingRef.current = false; setSaving(false); }
  }
  return open ? <Modal title="保存修改后离开？" subtitle={`${options.label}有未保存的修改。`} onClose={() => finish(false)}>
    <p>保存成功后将继续刚才的操作；不保存会放弃本次修改。</p>
    {error && <p className="wb-inline-error" role="alert">{error}</p>}
    <div className="modal-actions draft-actions">
      <button data-dialog-autofocus className="button secondary" disabled={saving} onClick={() => finish(false)}>继续编辑</button>
      <button className="button secondary danger" disabled={saving} onClick={() => { current.current.discard(); finish(true); }}>不保存并离开</button>
      <button className="button primary" disabled={saving} onClick={() => void saveAndLeave()}>{saving ? '正在保存…' : '保存并离开'}</button>
    </div>
  </Modal> : null;
}
