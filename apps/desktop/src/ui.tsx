import { useEffect, useRef, type ReactNode } from 'react';
import { ArrowUpRight, BookOpen, X, type LucideIcon } from 'lucide-react';
import type { Paper } from './data';
import { statusLabels } from './data';
import { useApp } from './context';
import {rpc} from './research-api';

export function IconButton({ icon: Icon, label, onClick, active = false }: { icon: LucideIcon; label: string; onClick: () => void; active?: boolean }) { return <button className={`icon-button ${active ? 'active' : ''}`} aria-label={label} title={label} onClick={onClick}><Icon size={17} /></button>; }
export function Badge({ paper }: { paper: Paper }) { return <span className={`status ${paper.status}`}><i />{statusLabels[paper.status]}</span>; }
export function Empty({ title, text, children }: { title: string; text: string; children?: ReactNode }) { return <div className="empty"><span className="empty-icon"><BookOpen size={28} strokeWidth={1.4} /></span><h3>{title}</h3><p>{text}</p>{children}</div>; }
export function Modal({ title, subtitle, children, onClose, className }: { title: string; subtitle?: string; children: ReactNode; onClose: () => void; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement; ref.current?.showModal(); return () => { previous?.focus(); }; }, []);
  return <dialog className={`modal ${className||''}`} ref={ref} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === ref.current) onClose(); }}><div className="modal-content"><div className="modal-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><IconButton icon={X} label="关闭弹窗" onClick={onClose} /></div>{children}</div></dialog>;
}
export function EvidenceCard({ paper, index = 1, onOpen }: { paper: Paper; index?: number; onOpen?: () => void }) {
  const { openPaper } = useApp();
  return <button className="evidence-card" onClick={onOpen || (() => openPaper(paper))}><span className="evidence-number">{index.toString().padStart(2, '0')}</span><div><span className="eyebrow">{paper.year} · {paper.status === 'indexed' ? '全文示例' : '摘要示例'}</span><h4>{paper.title}</h4><p>{paper.journal}</p><span className="evidence-link">查看来源 <ArrowUpRight size={13} /></span></div></button>;
}
export async function downloadText(project:string, name: string, value: string): Promise<string> {
  const safeName=name.replace(/[\\/:*?"<>|\x00-\x1f]/g,'').slice(0,120);
  const r=await rpc<{path:string}>('storage.markdown',{project,name:safeName,content:value});
  return `已导出：${r.path}`;
}
