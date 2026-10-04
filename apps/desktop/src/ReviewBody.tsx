import {evidenceMarkdownComponents} from './evidenceMarkdown';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type {Components} from 'react-markdown';

export type BodyBlock={type:'markdown';text:string}|{type:'notice';text:string}|{type:'table';anchor:string;label:string;title:string;html:string;notes:string}|{type:'resource';anchor?:string;resourceId:string;kind:'table'|'figure';label:string;pmid:string;html?:string;dataUrl?:string;context?:{text:string}[]};
export default function ReviewBody({markdown,blocks,onObjectLink,onCitation}:{markdown:string;blocks?:BodyBlock[];onObjectLink?:(anchor:string)=>void;onCitation?:(pmid:string)=>void}){
 const cite=(text:string)=>onCitation?text.replace(/\(PMID:\s*(\d+(?:\s*,\s*\d+)*)\)/g,(_,ids:string)=>`(PMID: ${ids.split(/\s*,\s*/).map(id=>`[${id}](#cite-pmid-${id})`).join(', ')})`):text;
 const html=(text:string)=>onCitation?text.replace(/\(PMID:\s*(\d+(?:\s*,\s*\d+)*)\)/g,(_,ids:string)=>`(PMID: ${ids.split(/\s*,\s*/).map(id=>`<button class="qa-citation" data-qa-pmid="${id}">${id}</button>`).join(', ')})`):text;
 const components:Components=onCitation?{...evidenceMarkdownComponents,a:({href,children})=>href?.match(/^#cite-pmid-\d+$/)?<button className="qa-citation" title="查看引用的原文与图表" onClick={()=>onCitation(href.slice(11))}>{children}</button>:<a href={href}>{children}</a>}:evidenceMarkdownComponents;
 return <div onClick={event=>{
  const citation=event.target instanceof Element?event.target.closest('[data-qa-pmid]'):null;
  if(citation&&onCitation){onCitation(citation.getAttribute('data-qa-pmid')!);return;}
  const link=event.target instanceof Element?event.target.closest('a'):null;
  const href=link?.getAttribute('href');if(!href||!/^#obj_[a-f0-9]{24}$/.test(href))return;
  event.preventDefault();const target=event.currentTarget.querySelector(href)||document.getElementById(href.slice(1));
  if(target)target.scrollIntoView({block:'start'});else onObjectLink?.(href.slice(1));
 }}>{(blocks??[{type:'markdown',text:markdown}]).map((b,i)=>b.type==='markdown'
  ?<Markdown key={i} remarkPlugins={[remarkGfm]} components={components}>{cite(b.text)}</Markdown>
  :b.type==='notice'?<aside className="object-notice" key={i}>{b.text}</aside>
  :b.type==='table'?<figure className="body-table" id={b.anchor} key={i}>
    <figcaption><Markdown remarkPlugins={[remarkGfm]} components={components}>{cite(`${b.label} · ${b.title}`)}</Markdown></figcaption>
    <div className="body-resource-table" dangerouslySetInnerHTML={{__html:html(b.html)}}/>
    {b.notes&&<div className="table-notes"><Markdown remarkPlugins={[remarkGfm]} components={components}>{cite(b.notes)}</Markdown></div>}
   </figure>
  :<figure className="body-resource" id={b.anchor} data-resource-id={b.resourceId} key={i}>
    {b.kind==='table'?<div className="body-resource-table" dangerouslySetInnerHTML={{__html:b.html||''}}/>:<img src={b.dataUrl} alt={`${b.label} · PMID ${b.pmid}`}/>}
    <figcaption>{b.label} · 原文资源 (PMID: {onCitation?<button className="qa-citation" onClick={()=>onCitation(b.pmid)}>{b.pmid}</button>:b.pmid})</figcaption>
    {!!b.context?.length&&<details><summary>原文邻近文字（不保证为完整图注）</summary>{b.context.map((p,j)=><Markdown key={j} remarkPlugins={[remarkGfm]} components={evidenceMarkdownComponents}>{p.text}</Markdown>)}</details>}
   </figure>)}</div>;
}
