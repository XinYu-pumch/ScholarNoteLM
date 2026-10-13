import {t as tr} from './i18n';
import {createContext,memo,useContext,useEffect,useId,useMemo,useState} from 'react';
import Markdown,{type Components} from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {Check,ChevronDown,Copy,LoaderCircle,Send,Sparkles} from 'lucide-react';
import {proposalBlocks,queryTextKey} from './search-proposals';
import type {ChatMessage,Proposal} from './research-api';

type Actions={added:Set<string>;adding:Set<string>;add:(q:Proposal)=>void;copy:(text:string)=>void};
export const ProposalActions=createContext<Actions>({added:new Set(),adding:new Set(),add:()=>{},copy:()=>{}});
const Blocks=createContext<ReturnType<typeof proposalBlocks>>([]);
const plugins=[remarkGfm];

const Foldout=memo(function Foldout({text,streaming=false,title='思考过程'}:{text:string;streaming?:boolean;title?:string}){
 const [open,setOpen]=useState(streaming);const id=useId();
 useEffect(()=>setOpen(streaming),[streaming]);
 return <section className={`chat-foldout ${title==='思考过程'?'chat-reasoning':'chat-explanation'}`}><button type="button" className="chat-foldout-toggle" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(v=>!v)}><Sparkles size={13}/><span>{streaming?tr("正在思考"):tr(title)}</span><span className="foldout-action">{open?tr("收起"):tr("展开")}</span><ChevronDown size={14}/></button><div id={id} className="chat-foldout-content" hidden={!open}>{open&&(streaming?<div className="chat-stream-reasoning">{text}</div>:<Markdown remarkPlugins={plugins}>{text}</Markdown>)}</div></section>;
});

const ProposalCard=memo(function ProposalCard({q,index=0,heading=false}:{q:Proposal;index?:number;heading?:boolean}){
 const actions=useContext(ProposalActions);const key=queryTextKey(q.text),added=actions.added.has(key),adding=actions.adding.has(key);
 return <section className="chat-proposal-action">{heading&&<header><span className="proposal-number">{String(index+1).padStart(2,'0')}</span><h4>{q.name}</h4><span className="proposal-source">PubMed</span></header>}{q.purpose&&<p className="proposal-purpose">{q.purpose}</p>}<pre className="proposal-query"><code>{q.text}</code></pre><footer><span>{q.meshCheck?.some(t=>!t.verified)?tr("部分 MeSH 名称待核验"):tr("可复制或发送到文献来源")}</span><div><button type="button" className="text-button" aria-label={tr("复制检索式：{p0}",{p0:q.name})} onClick={()=>actions.copy(q.text)}><Copy size={13}/>{tr("复制检索式")}</button><button type="button" className="button secondary compact" aria-label={tr("发送到文献来源：{p0}",{p0:q.name})} disabled={adding||added} onClick={()=>actions.add(q)}>{added?<><Check size={13}/>{tr("已加入")}</>:adding?<><LoaderCircle className="spin" size={13}/>{tr("正在加入…")}</>:<><Send size={13}/>{tr("发送到文献来源")}</>}</button></div></footer></section>;
});
// Stable component identity is essential: replacing this function during a token
// update would unmount buttons between pointerdown and click.
const ProposalPre:NonNullable<Components['pre']>=({children,node})=>{
 const blocks=useContext(Blocks),offset=node?.position?.start.offset;
 const block=blocks.find(b=>offset!==undefined&&offset>=b.offset&&offset<=b.offset+3);
 return block?<ProposalCard q={block.proposal}/>:<div className="chat-code-block">{children}</div>;
};
const components:Components={pre:ProposalPre};
const MarkdownBody=memo(function MarkdownBody({text}:{text:string}){return <Markdown remarkPlugins={plugins} components={components}>{text}</Markdown>;});

export default memo(function SearchResponse({message:m,live}:{message:ChatMessage;live:boolean}){
 const blocks=useMemo(()=>proposalBlocks(m),[m.text,m.result?.queries]);
 const proposals=m.result?.queries||[];
 const remaining=useMemo(()=>proposals.filter(q=>!blocks.some(b=>queryTextKey(b.proposal.text)===queryTextKey(q.text))),[blocks,m.result?.queries]);
 const legacy=proposals.length>0&&!blocks.length&&!proposals.some(q=>m.text.includes(q.text));
 return <>{m.reasoning&&<Foldout text={m.reasoning} streaming={live}/>}<div className="chat-markdown"><Blocks.Provider value={blocks}>{legacy?<Foldout text={m.text} title={tr("策略说明")}/>:<MarkdownBody text={m.text}/>}</Blocks.Provider>{live&&!m.text&&!m.reasoning&&<p className="quiet">{tr("正在连接模型…")}</p>}</div>{m.error&&<p className="chat-message-error">{tr(m.error)}</p>}{m.cancelled&&<small className="quiet">{tr("已停止生成，已保留接收到的内容。")}</small>}{!live&&remaining.map((q,index)=><ProposalCard key={q.id} q={q} index={index} heading/>)}</>;
});
