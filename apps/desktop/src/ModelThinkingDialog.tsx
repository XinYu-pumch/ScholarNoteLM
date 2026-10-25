import {useEffect,useRef,useState} from 'react';
import {t as tr} from './i18n';
import DraftModal,{DraftCancel} from './DraftModal';
import Select from './Select';
import {rpc,message,type Profile,type SettingsData,type ThinkingSelection,type ConnectionTestResult} from './research-api';

export function ConnectionTestDetails({result}:{result:ConnectionTestResult}){
 const thinking=result.thinking;
 const probe=thinking?.probe;
 const explanation=probe?.status==='rejected'?'错误值被服务端明确拒绝，说明该参数被校验；这不能证明合法档位的实际推理强度。':probe?.status==='accepted'?'错误值也返回了正文；参数可能被忽略、移除或替换，无法确认档位生效。':probe?.status==='inconclusive'?'本次错误参数检查无法判断；超时、限流或未明确指出参数的错误不作为支持证据。':probe?.status==='not_applicable'?'当前没有可验证的显式普通模型思考参数。':null;
 return <div className="thinking-test-details" role="status">
  <p>{tr('连接通过 · {p0} 秒',{p0:result.seconds})}</p>
  {thinking&&<><p>{thinking.reasoningCharacters>0?tr('已接收思考文本：{p0} 字符',{p0:thinking.reasoningCharacters}):tr('未收到思考文本；这不表示模型没有思考。')}{thinking.reasoningCharacters>0&&' · '+tr(thinking.outputKind==='summary'?'思考摘要':'服务端推理文本')}</p>
  <p>{thinking.reasoningTokens==null?tr('服务端未报告思考 token 用量。'):tr('服务端报告思考 token：{p0}',{p0:thinking.reasoningTokens})}</p>
  <details><summary>{tr('本次发送的思考参数')}</summary><pre>{Object.keys(thinking.parameters).length?JSON.stringify(thinking.parameters,null,2):tr('服务端默认：未发送额外思考参数')}</pre></details>
  {explanation&&<p>{tr(explanation)}{probe?.parameter&&<><br/><code>{probe.parameter}</code>{probe.httpStatus&&` · HTTP ${probe.httpStatus}`}</>}</p>}
  <p className="quiet small">{tr('请求成功或收到思考文本，均不能单独证明所选强度被执行。')}</p></>}
 </div>;
}

export default function ModelThinkingDialog({model,profile,data,onApply,onClose}:{model:string;profile:Profile;data:SettingsData;onApply:(patch:Partial<Profile>)=>void;onClose:()=>void}){
 const [draft,setDraft]=useState(profile),[busy,setBusy]=useState(false),[error,setError]=useState(''),[test,setTest]=useState<ConnectionTestResult|null>(null);
 const revision=useRef(0);
 useEffect(()=>()=>{revision.current++;},[]);
 const ordinary=!profile.provider||profile.provider==='openai';
 const selected=draft.thinkingByModel?.[model];
 const preset=data.thinkingPresets?.find(p=>p.id===selected?.preset);
 const meta=data.providers?.find(p=>p.id===profile.provider)?.models?.[model]?.reasoning;
 const level=draft.reasoningByModel?.[model]||'';
 const update=(patch:Partial<Profile>)=>{revision.current++;setDraft(p=>({...p,...patch}));setTest(null);setError('');};
 const select=(value:ThinkingSelection|null)=>{const next={...draft.thinkingByModel};if(value)next[model]=value;else delete next[model];update({thinkingByModel:next});};
 const values=(p:Profile)=>[p.thinkingByModel?.[model],p.reasoningByModel?.[model],p.reasoningBudgetByModel?.[model]];
 const dirty=JSON.stringify(values(profile))!==JSON.stringify(values(draft));
 const apply=async()=>{
  if(!ordinary&&level==='budget'){
   const n=draft.reasoningBudgetByModel?.[model],budget=meta?.budget;
   if(n==null||!Number.isInteger(n)||n<(budget?.min||1)||(budget?.max!=null&&n>budget.max)){setError(tr('请填写此模型支持的正整数思考 token 预算'));throw Error(tr('请填写此模型支持的正整数思考 token 预算'));}
  }
  if(dirty)onApply({thinkingByModel:draft.thinkingByModel,reasoningByModel:draft.reasoningByModel,reasoningBudgetByModel:draft.reasoningBudgetByModel});
  onClose();
 };
 const run=async(probe=false)=>{
  const token=++revision.current;setBusy(true);setError('');setTest(null);
  try{const result=await rpc<ConnectionTestResult>('llm.test',{profile:{...draft,model,testThinkingProbe:probe}});if(token===revision.current)setTest(result);}
  catch(e){if(token===revision.current)setError(message(e));}
  finally{setBusy(false);}
 };
 return <DraftModal title="思考设置" subtitle={model} className="model-thinking-dialog" onClose={onClose} dirty={dirty} busy={busy} save={apply} saveLabel="应用">
  <div className="wb-form">
   {ordinary?<><label>{tr('思考预设')}<Select aria-label={tr('{p0} 思考预设',{p0:model})} value={selected?.preset||''} disabled={busy} onChange={e=>{const next=data.thinkingPresets?.find(p=>p.id===e.target.value);select(next?{preset:next.id,level:next.defaultLevel,...(next.output?.defaultMode&&next.output.defaultMode!=='default'?{output:next.output.defaultMode}:{})}:null);}}><option value="">{tr('服务端默认')}</option>{data.thinkingPresets?.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}{selected&&!preset&&<option value={selected.preset}>{tr('预设不可用')}</option>}</Select></label>
   {preset&&<><label>{tr('思考强度')}<Select aria-label={tr('{p0} 思考强度',{p0:model})} disabled={busy} value={selected?.level||preset.defaultLevel} onChange={e=>select({...selected!,level:e.target.value})}>{preset.levels.map(value=><option key={value} value={value}>{value}</option>)}</Select></label>{preset.note&&<p className="quiet small">{preset.note}</p>}
   <label>{tr('思考输出')}<Select aria-label={tr('{p0} 思考输出',{p0:model})} disabled={busy||!preset.output||preset.output.modes.length<2} value={selected?.output||'default'} onChange={e=>{const next={...selected!};if(e.target.value==='default')delete next.output;else next.output=e.target.value;select(next);}}>{(preset.output?.modes||['default']).map(value=><option key={value} value={value}>{tr(value==='summary'?'请求思考摘要':value==='off'?'不请求思考摘要':'预设默认')}</option>)}</Select></label><p className="quiet small">{tr(preset.output?.note||'思考输出由服务端决定。')}</p></>}
   {!preset&&<p className="quiet small">{tr('未选择预设时保持普通请求；服务端返回的思考文本仍会自动接收。')}</p>}</>:<><label>{tr('思考强度')}<Select aria-label={tr('{p0} 思考强度',{p0:model})} disabled={busy||!meta?.levels?.length} value={level} onChange={e=>{const next={...draft.reasoningByModel};if(e.target.value)next[model]=e.target.value;else delete next[model];update({reasoningByModel:next});}}><option value="">{tr('服务端默认')}</option>{meta?.levels?.map(value=><option key={value} value={value}>{value}</option>)}</Select></label>
   {meta?.budget&&level==='budget'&&<label>{tr('思考 token 预算')}<input type="number" min={meta.budget.min} max={meta.budget.max} step={1} disabled={busy} aria-label={tr('{p0} 思考 token 预算',{p0:model})} value={draft.reasoningBudgetByModel?.[model]??''} onChange={e=>{const next={...draft.reasoningBudgetByModel};if(e.target.value==='')delete next[model];else next[model]=Number(e.target.value);update({reasoningBudgetByModel:next});}}/></label>}
   <p className="quiet small">{tr(meta?.note||'使用供应商模块的官方思考设置，思考输出由模块及服务端决定。')}</p>{meta?.output?.note&&<p className="quiet small">{tr(meta.output.note)}</p>}</>}
   <div className="thinking-test-actions"><button className="button secondary compact" disabled={busy||!draft.baseUrl.trim()} onClick={()=>void run()}>{tr('测试当前设置')}</button>{ordinary&&<button className="button secondary compact" disabled={busy||!selected||!draft.baseUrl.trim()} onClick={()=>void run(true)}>{tr('深入验证参数')}</button>}</div>
   {ordinary&&<p className="quiet small">{tr('深入验证会先发送正常请求，再用一个错误思考参数作对照；不会保存错误值。')}</p>}
   {busy&&<p role="status">{tr('正在测试…')}</p>}{error&&<p className="wb-alert" role="alert">{tr(error)}</p>}{test&&<ConnectionTestDetails result={test}/>}
   <p className="quiet small">{tr('应用后仍需点击保存配置。')}</p>
  </div>
  <div className="modal-actions"><DraftCancel className="button secondary" disabled={busy}>{tr('取消')}</DraftCancel><button className="button primary" disabled={busy} onClick={()=>void apply().catch(()=>{})}>{tr('应用')}</button></div>
 </DraftModal>;
}
