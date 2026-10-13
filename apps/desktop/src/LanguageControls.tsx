import {useApp} from './context';
import {t as tr} from './i18n';
import ContentLanguage from './ContentLanguage';
export function LanguageSwitch(){const {state,updateState}=useApp();return <div className="language-switch" role="group" aria-label={tr('界面语言')}><button type="button" lang="zh-CN" aria-pressed={state.uiLanguage!=='en'} onClick={()=>updateState(s=>({...s,uiLanguage:'zh'}))}>中文</button><button type="button" lang="en" aria-pressed={state.uiLanguage==='en'} onClick={()=>updateState(s=>({...s,uiLanguage:'en'}))}>EN</button></div>;}
export function LanguagePreferences(){const {state,updateState}=useApp();return <section className="language-preferences"><h3>{tr('语言')}</h3><ContentLanguage label="新内容默认语言" value={state.defaultContentLanguage||'zh'} onChange={value=>updateState(s=>({...s,defaultContentLanguage:value}))}/><p className="quiet small">{tr('仅用于新综述和新对话，不改变已有内容。界面语言可在右上角独立切换。')}</p></section>;}
