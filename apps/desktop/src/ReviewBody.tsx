import {t as tr} from './i18n';
import {useState} from 'react';
import {useApp} from './context';
import {ReaderLink} from './Reader';
import {Modal} from './ui';
import {evidenceMarkdownComponents} from './evidenceMarkdown';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type {Components} from 'react-markdown';

export type BodyBlock={type:'markdown';text:string}|{type:'notice';text:string}|{type:'table';anchor:string;label:string;title:string;html:string;notes:string}|{type:'resource';anchor?:string;resourceId:string;kind:'table'|'figure';label:string;pmid:string;html?:string;dataUrl?:string;context?:{text:string}[]};
export default function ReviewBody({markdown,blocks,onObjectLink,onCitation}:{markdown:string;blocks?:BodyBlock[];onObjectLink?:(anchor:string)=>void;onCitation?:(pmid:string)=>void}){
 const [citation,setCitation]=useState('');const {project}=useApp();
 const showCitation=onCitation||setCitation;const paper=project.papers.find(p=>p.id===`PMID-${citation}`);
 const cite=(text:string)=>text.replace(/\(PMID:\s*(\d+(?:\s*,\s*\d+)*)\)/g,(_,ids:string)=>`(PMID: ${ids.split(/\s*,\s*/).map(id=>`[${id}](#cite-pmid-${id})`).join(', ')})`);
 const html=(text:string)=>text.replace(/\(PMID:\s*(\d+(?:\s*,\s*\d+)*)\)/g,(_,ids:string)=>`(PMID: ${ids.split(/\s*,\s*/).map(id=>`<button class="qa-citation" data-qa-pmid="${id}">${id}</button>`).join(', ')})`);
 const components:Components={...evidenceMarkdownComponents,a:({href,children})=>href?.match(/^#cite-pmid-\d+$/)?<button className="qa-citation" title={tr("查看引用的原文与图表")} onClick={()=>showCitation(href.slice(11))}>{children}</button>:<a href={href}>{children}</a>};
 return <div onClick={event=>{
  const citation=event.target instanceof Element?event.target.closest('[data-qa-pmid]'):null;
  if(citation){showCitation(citation.getAttribute('data-qa-pmid')!);return;}
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
    <figcaption>{tr(b.label)} {tr("· 原文资源 (PMID:")}{<button className="qa-citation" onClick={()=>showCitation(b.pmid)}>{b.pmid}</button>})</figcaption>
    {!!b.context?.length&&<details><summary>{tr("原文邻近文字（不保证为完整图注）")}</summary>{b.context.map((p,j)=><Markdown key={j} remarkPlugins={[remarkGfm]} components={evidenceMarkdownComponents}>{p.text}</Markdown>)}</details>}
   </figure>)}{citation&&<Modal title={tr("引用文献")} onClose={()=>setCitation('')}><h3>{paper?.title||`PMID ${citation}`}</h3>{paper&&<p className="quiet">{paper.journal} · {paper.year}</p>}<ReaderLink pmid={citation}/></Modal>}</div>;
}
