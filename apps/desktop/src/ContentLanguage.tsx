import Select from './Select';
import {t,type Language} from './i18n';
export default function ContentLanguage({value,onChange,disabled=false,label='回答语言'}:{value:Language;onChange:(value:Language)=>void;disabled?:boolean;label?:string}){
 return <label className="content-language"><span>{t(label)}</span><Select aria-label={t(label)} value={value} disabled={disabled} onChange={e=>onChange(e.target.value as Language)}><option value="zh">中文</option><option value="en">English</option></Select></label>;
}
