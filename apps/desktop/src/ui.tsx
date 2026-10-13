import { useEffect, useId, useRef, type ReactNode } from 'react';
import { BookOpen, X, type LucideIcon } from 'lucide-react';
import type { Paper } from './data';
import { statusLabels } from './data';



export function IconButton({ icon: Icon, label, onClick, active = false }: { icon: LucideIcon; label: string; onClick: () => void; active?: boolean }) { return <button className={`icon-button ${active ? 'active' : ''}`} aria-label={label} title={label} onClick={onClick}><Icon size={17} /></button>; }
export function Badge({ paper }: { paper: Paper }) { return <span className={`status ${paper.status}`}><i />{statusLabels[paper.status]}</span>; }
export function Empty({ title, text, children }: { title: string; text: string; children?: ReactNode }) { return <div className="empty"><span className="empty-icon"><BookOpen size={28} strokeWidth={1.4} /></span><h3>{title}</h3><p>{text}</p>{children}</div>; }
export function Modal({ title, subtitle, children, onClose, className }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId=useId(), subtitleId=useId();
  useEffect(() => { const previous = document.activeElement as HTMLElement; ref.current?.showModal(); ref.current?.querySelector<HTMLElement>('[data-dialog-autofocus]')?.focus(); return () => { if(previous?.isConnected)previous.focus(); }; }, []);
  return <dialog aria-labelledby={titleId} aria-describedby={subtitle?subtitleId:undefined} className={`modal ${className||''}`} ref={ref} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === ref.current) onClose(); }}><div className="modal-content"><div className="modal-heading"><div><h2 id={titleId}>{title}</h2>{subtitle && <p id={subtitleId}>{subtitle}</p>}</div><IconButton icon={X} label="关闭弹窗" onClick={onClose} /></div>{children}</div></dialog>;
}
