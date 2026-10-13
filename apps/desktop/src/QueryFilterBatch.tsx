import Field from './Field';
import {useRef,useState} from 'react';
import {Check,LoaderCircle} from 'lucide-react';

import DraftModal,{DraftCancel} from './DraftModal';
import {defaultFilters,message,type Filters,type Query} from './research-api';

export type FilterBatch={dates?:Pick<Filters,'start'|'end'>;jcr?:Pick<Filters,'jcr'|'quartiles'|'unknown'>};
export default function QueryFilterBatch({queries,onApply,onClose}:{queries:Query[];onApply:(filters:FilterBatch)=>Promise<void>;onClose:()=>void}){
 const targets=queries.filter(q=>!q.archived&&q.source!=='zotero'),searchable=targets.filter(q=>q.source!=='import');
 const [filters,setFilters]=useState(()=>{
  const f=defaultFilters();
  if(searchable.length&&searchable.every(q=>q.filters.start===searchable[0].filters.start&&q.filters.end===searchable[0].filters.end))Object.assign(f,{start:searchable[0].filters.start,end:searchable[0].filters.end});
  if(targets.length&&targets.every(q=>q.filters.jcr===targets[0].filters.jcr&&JSON.stringify([...q.filters.quartiles].sort())===JSON.stringify([...targets[0].filters.quartiles].sort())&&q.filters.unknown===targets[0].filters.unknown))Object.assign(f,{jcr:targets[0].filters.jcr,quartiles:targets[0].filters.quartiles,unknown:targets[0].filters.unknown});
  return f;
 });
 const [dates,setDates]=useState(!!searchable.length),[jcr,setJcr]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const baseline=useRef(JSON.stringify({filters,dates,jcr}));
 async function persist(){
  if(!dates&&!jcr)throw new Error('至少选择一种筛选条件');
  if(dates&&filters.start&&filters.end&&filters.start>filters.end)throw new Error('开始日期不能晚于结束日期');
  await onApply({...dates?{dates:{start:filters.start,end:filters.end}}:{},...jcr?{jcr:{jcr:filters.jcr,quartiles:filters.quartiles,unknown:filters.unknown}}:{}});onClose();
 }
 async function save(){setBusy(true);setError('');try{await persist();}catch(e){setError(message(e));}finally{setBusy(false);}}
 return <DraftModal dirty={JSON.stringify({filters,dates,jcr})!==baseline.current} busy={busy} save={persist} title="批量筛选" subtitle={`应用到当前 ${targets.length} 条未归档检索式（含停用条目），之后仍可逐条调整。`} onClose={()=>{if(!busy)onClose();}}>
  <form className="batch-filter-form" onSubmit={e=>{e.preventDefault();void save();}}>
   <section><label className="batch-filter-toggle"><input type="checkbox" checked={dates} disabled={busy||!searchable.length} onChange={e=>setDates(e.target.checked)}/>统一日期</label><fieldset disabled={busy||!dates}><div className="wb-form-grid"><Field>发表日期 · 开始<input type="date" value={filters.start} onChange={e=>setFilters({...filters,start:e.target.value})}/></Field><Field>发表日期 · 结束<input type="date" value={filters.end} onChange={e=>setFilters({...filters,end:e.target.value})}/></Field></div><p className="quiet small">留空表示不限日期。日期改变后，已有检索结果需重新执行。</p></fieldset></section>
   <section><label className="batch-filter-toggle"><input type="checkbox" checked={jcr} disabled={busy} onChange={e=>setJcr(e.target.checked)}/>统一 JCR 分区</label><fieldset disabled={busy||!jcr}><div className="wb-quartiles">{['Q1','Q2','Q3','Q4'].map(q=><label key={q}><input type="checkbox" checked={filters.jcr&&filters.quartiles.includes(q)} onChange={e=>{const quartiles=e.target.checked?[...(filters.jcr?filters.quartiles:[]),q]:filters.quartiles.filter(v=>v!==q);setFilters({...filters,quartiles,jcr:!!quartiles.length});}}/>{q}</label>)}</div><p className="quiet small">未匹配期刊或无分区的文献不计入目标数量。</p><p className="quiet small">不选表示不限分区。数量不足时，可点击“更新检索”。</p></fieldset></section>
   {targets.length>searchable.length&&<p className="quiet small">其中 {targets.length-searchable.length} 条为导入 XML，仅应用 JCR，保留原日期条件。</p>}
   <p className="quiet small">只替换勾选的条件；检索式内容、排序和数量保持各自设置。</p>
   {error&&<div className="wb-alert" role="alert">{error}</div>}
   <div className="modal-actions"><DraftCancel className="button secondary" disabled={busy}>取消</DraftCancel><button type="submit" className="button primary" disabled={busy||(!dates&&!jcr)||!targets.length}>{busy?<LoaderCircle className="spin" size={15}/>:<Check size={15}/>} {busy?'正在应用…':'应用到全部检索式'}</button></div>
  </form>
 </DraftModal>;
}
