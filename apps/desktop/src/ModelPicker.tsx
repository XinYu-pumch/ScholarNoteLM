import {t as tr} from './i18n';
import {useQuery} from './useQuery';
import {useEffect,useState} from 'react';
import Select from './Select';
import {type Profile} from './research-api';
export type ModelSelection={profileId:string;model:string};
export const defaultSelection:ModelSelection={profileId:'',model:''};
const emptyPool:{profiles:Profile[];activeProfile:string}={profiles:[],activeProfile:''};
export function useModelPool(){
 const result=useQuery<{profiles:Profile[];activeProfile:string}>('profile.list');
 return result.data||emptyPool;
}

export function useWorkspaceModel(scope:string,fallback:ModelSelection=defaultSelection){
 const pool=useModelPool();const key=`scholar-model:${scope}`;
 const read=():ModelSelection|null=>{try{const v=JSON.parse(localStorage.getItem(key)||'null');return v&&typeof v.profileId==='string'&&typeof v.model==='string'?v:null;}catch{return null;}};
 const [saved,setSaved]=useState(()=>({key,value:read()}));
 useEffect(()=>setSaved({key,value:read()}),[key]);
 // Preserve an explicit choice (including “default”); otherwise restore the saved task model.
 const selection=(saved.key===key?saved.value:read())??fallback;
 const choose=(value:ModelSelection)=>{setSaved({key,value});localStorage.setItem(key,JSON.stringify(value));};
 const p=pool.profiles.find(p=>p.id===(selection.profileId||pool.activeProfile));
 const model=selection.model||p?.model||'';
 const valid=!!p&&!!model&&(p.models||[p.model]).includes(model);
 return {selection,choose,ready:valid,label:valid?`${p!.name}/${model}`:''};
}
export default function ModelPicker({label,value,onChange,disabled=false}:{label:string;value:ModelSelection;onChange:(value:ModelSelection)=>void;disabled?:boolean}){
 const {profiles,activeProfile}=useModelPool();const current=profiles.find(p=>p.id===activeProfile);
 const choices=profiles.flatMap(p=>(p.models||[p.model]).filter(Boolean).map(model=>({value:JSON.stringify([p.id,model]),label:`${p.name} / ${model}`})));
 const selected=value.profileId?JSON.stringify([value.profileId,value.model||profiles.find(p=>p.id===value.profileId)?.model||'']):'';
 return <label className="workspace-model-picker"><span>{tr(label)}</span><Select aria-label={tr(label)} value={selected} disabled={disabled} onChange={e=>{const [profileId,model]=e.target.value?JSON.parse(e.target.value):['',''];onChange({profileId,model});}}><option value="">{current?.model?tr("默认 · {p0} / {p1}",{p0:current.name,p1:current.model}):tr("默认 · 尚未配置模型")}</option>{selected&&!choices.some(c=>c.value===selected)&&<option value={selected} disabled>{tr("所选模型已移除，请重新选择")}</option>}{choices.map(c=><option key={c.value} value={c.value}>{tr(c.label)}</option>)}</Select></label>;
}
