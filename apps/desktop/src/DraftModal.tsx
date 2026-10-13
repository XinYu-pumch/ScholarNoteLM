import {createContext,useContext,type ReactNode,type ButtonHTMLAttributes} from 'react';
import {Modal} from './ui';
import {useDraftGuard} from './useUnsavedChanges';

const CloseDraft=createContext<()=>void>(()=>{});
export function DraftCancel(props:ButtonHTMLAttributes<HTMLButtonElement>){const close=useContext(CloseDraft);return <button {...props} type="button" onClick={close}/>;}

/** Explicit saves, Escape, backdrop, navigation and native quit share one draft. */
export default function DraftModal({title,subtitle,children,onClose,dirty,busy=false,save,saveLabel,className}:{title:string;subtitle?:string;children:ReactNode;onClose:()=>void;dirty:boolean;busy?:boolean;save:()=>Promise<void>;saveLabel?:string;className?:string}) {
 const guard=useDraftGuard({label:title,scope:'dialog',dirty,busy,save,discard:onClose,saveLabel});
 return <><Modal title={title} subtitle={subtitle} className={className} busy={busy} onClose={()=>guard.leave(onClose)}><CloseDraft.Provider value={()=>guard.leave(onClose)}>{children}</CloseDraft.Provider></Modal>{guard.dialog}</>;
}
