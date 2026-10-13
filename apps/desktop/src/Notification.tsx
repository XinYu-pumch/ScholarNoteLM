import {Check, CircleAlert, Info, TriangleAlert, X} from 'lucide-react';
export type NoticeTone = 'info' | 'success' | 'warning' | 'error';
export type Notice = {message: string; tone: NoticeTone; key?: string; scope?: string};
export function Notification({notice, onClose}: {notice: Notice | null; onClose: () => void}) {
  if (!notice) return null;
  const Icon = {info: Info, success: Check, warning: TriangleAlert, error: CircleAlert}[notice.tone];
  return <div className={`toast toast-${notice.tone}`}>
    <Icon size={17} aria-hidden="true"/>
    <span role={notice.tone === 'error' ? 'alert' : 'status'}>{notice.message}</span>
    <button className="icon-button" aria-label="关闭通知" onClick={onClose}><X size={16}/></button>
  </div>;
}
