import {t as tr} from './i18n';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { BookOpen, X, type LucideIcon } from 'lucide-react';
import type { Paper } from './data';
import { statusLabels } from './data';



export function IconButton({ icon: Icon, label, onClick, active = false, disabled=false }: { icon: LucideIcon; label: string; onClick: () => void; active?: boolean; disabled?:boolean }) { return <button type="button" disabled={disabled} className={`icon-button ${active ? 'active' : ''}`} aria-label={tr(label)} title={tr(label)} onClick={onClick}><Icon size={17} /></button>; }
export function Badge({ paper }: { paper: Paper }) { return <span className={`status ${paper.status}`}><i />{tr(statusLabels[paper.status])}</span>; }
export function Empty({ title, text, children }: { title: string; text: string; children?: ReactNode }) { return <div className="empty"><span className="empty-icon"><BookOpen size={28} strokeWidth={1.4} /></span><h3>{tr(title)}</h3><p>{tr(text)}</p>{children}</div>; }
export function Modal({ title, subtitle, children, onClose, className, busy=false }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; className?: string; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId=useId(), subtitleId=useId();
  const backdrop=useRef(false);
  const opener=useRef<HTMLElement|null>(null);
  useEffect(() => {
    const active=document.activeElement as HTMLElement;
    // StrictMode replays effects while the dialog is already focused.
    if(!ref.current?.contains(active))opener.current=active;
    ref.current?.showModal();
    (ref.current?.querySelector<HTMLElement>('[data-dialog-autofocus]')||ref.current?.querySelector<HTMLElement>('input:not([type=hidden]):not(:disabled),textarea:not(:disabled),[role=combobox]:not(:disabled)'))?.focus();
    return ()=>{requestAnimationFrame(()=>{const active=document.activeElement;if(opener.current?.isConnected&&(!active||active===document.body||!active.isConnected))opener.current.focus({preventScroll:true});});};
  },[]);
  const close=()=>{if(!busy)onClose();};
  return <dialog aria-busy={busy||undefined} aria-labelledby={titleId} aria-describedby={subtitle?subtitleId:undefined} className={`modal ${className||''}`} ref={ref} onCancel={e => { e.preventDefault(); close(); }} onPointerDown={e=>{backdrop.current=e.target===ref.current;}} onClick={e => { if (e.target === ref.current&&backdrop.current) close(); backdrop.current=false; }}><div className="modal-content"><div className="modal-heading"><div><h2 id={titleId}>{tr(title)}</h2>{subtitle && <p id={subtitleId}>{subtitle}</p>}</div><IconButton icon={X} label={tr("关闭弹窗")} disabled={busy} onClick={close} /></div>{children}</div></dialog>;
}
