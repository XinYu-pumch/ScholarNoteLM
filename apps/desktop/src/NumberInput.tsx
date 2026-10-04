import {useEffect,useRef,useState,type InputHTMLAttributes} from 'react';

// Keep an editable draft: clearing a numeric field must not send Number('') = 0.
export default function NumberInput({value,onChange,onBlur,allowEmpty=false,...props}:InputHTMLAttributes<HTMLInputElement>&{allowEmpty?:boolean}){
 const [draft,setDraft]=useState(String(value??''));const focused=useRef(false);
 useEffect(()=>{if(!focused.current)setDraft(String(value??''));},[value]);
 return <input {...props} type="number" value={draft} onFocus={()=>{focused.current=true;}}
  onChange={e=>{setDraft(e.target.value);if((e.target.value!==''||allowEmpty)&&e.target.validity.valid)onChange?.(e);}}
  onBlur={e=>{focused.current=false;if(e.target.value===''&&!allowEmpty||!e.target.validity.valid)setDraft(String(value??''));onBlur?.(e);}}/>;
}
