import {t as tr} from './i18n';
import type {ChatMessage,Proposal,Query} from './research-api';

export const queryTextKey=(text:string)=>text.trim().replace(/\s+/g,' ');
export const needsQueryRun=(q:Query)=>q.enabled&&!q.archived&&q.source!=='import'&&q.source!=='zotero'&&!!q.text.trim()&&(!q.xmlExists||!!q.stale);

/** Only closed fences are actionable, including while a reply is still streaming. */
export function proposalBlocks(message:ChatMessage):{offset:number;proposal:Proposal}[]{
 const blocks:{offset:number;proposal:Proposal}[]=[];
 const fence=/^ {0,3}(`{3,}|~{3,})([^\n]*)\r?\n/gm;
 let match:RegExpExecArray|null;
 while((match=fence.exec(message.text))){
  const marker=match[1],language=match[2].trim().toLowerCase();
  const close=new RegExp(`^ {0,3}${marker[0]}{${marker.length},}[ \\t]*\\r?$`,'gm');close.lastIndex=fence.lastIndex;
  const end=close.exec(message.text);if(!end)break;
  const text=message.text.slice(fence.lastIndex,end.index).trim();fence.lastIndex=close.lastIndex;
  const known=message.result?.queries?.find(q=>queryTextKey(q.text)===queryTextKey(text));
  const queryLike=/\[(?:tiab|mesh terms|mh|title\/abstract|tw)\]/i.test(text)&&/\b(?:AND|OR|NOT)\b/.test(text);
  if(!text||(!known&&language!=='pubmed'&&!(['','text','plaintext'].includes(language)&&queryLike)))continue;
  const title=[...message.text.slice(0,match.index).matchAll(/^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$/gm)].at(-1)?.[1]||tr("检索式 {p0}",{p0:blocks.length+1});
  blocks.push({offset:match.index,proposal:known||{id:`block-${match.index}`,name:title,text,purpose:''}});
 }
 return blocks;
}
