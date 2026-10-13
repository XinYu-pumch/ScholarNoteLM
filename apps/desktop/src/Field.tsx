import {Children,cloneElement,isValidElement,useId,useState,type ReactNode,type HTMLAttributes,type InputHTMLAttributes,type FocusEvent,type ChangeEvent,type InvalidEvent} from 'react';
/** Labels retain their existing layout; native validity gets persistent inline feedback. */
export default function Field({children,...props}:HTMLAttributes<HTMLLabelElement>){
 const id=useId(),[error,setError]=useState('');
 const control=(node:ReactNode):ReactNode=>{
  if(!isValidElement<InputHTMLAttributes<HTMLInputElement>>(node)||!['input','textarea'].includes(String(node.type)))return node;
  const p=node.props;
  const read=(element:HTMLInputElement)=>{
   const v=element.validity;
   return v.valid?'':v.valueMissing?'请填写此项':v.typeMismatch?'请检查输入格式':v.patternMismatch?'格式不正确，请按提示填写':v.rangeUnderflow?`不得小于 ${element.min}`:v.rangeOverflow?`不得大于 ${element.max}`:v.stepMismatch?'请填写允许的数值':element.validationMessage;
  };
  return cloneElement(node,{
   'aria-invalid':error?true:p['aria-invalid'],
   'aria-describedby':[p['aria-describedby'],error?id:undefined].filter(Boolean).join(' ')||undefined,
   onInvalid:(e:InvalidEvent<HTMLInputElement>)=>{e.preventDefault();setError(read(e.currentTarget));if(!e.currentTarget.form||e.currentTarget.form.querySelector(':invalid')===e.currentTarget)e.currentTarget.focus();p.onInvalid?.(e);},
   onBlur:(e:FocusEvent<HTMLInputElement>)=>{setError(read(e.currentTarget));p.onBlur?.(e);},
   onChange:(e:ChangeEvent<HTMLInputElement>)=>{if(error)setError(read(e.currentTarget));p.onChange?.(e);}
  });
 };
 return <label {...props}>{Children.map(children,control)}{error&&<span id={id} className="field-error" role="alert">{error}</span>}</label>;
}
