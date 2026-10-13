import {t as tr} from './i18n';
import {useEffect} from 'react';
import {useTabs} from './useTabs';
import {usePageState} from './page-memory';
import {useVectors} from './Vector';
import LiteratureWorkflow from './LiteratureWorkflow';
import {useMarkdown} from './markdown-api';
import {useDownloads,startDownload,downloadChanged} from './download-api';
import {PdfStatus,PdfDetails} from './Downloads';
import {rpc,message} from './research-api';
import Select from './Select';
import { useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronDown, Download, FileText, LayoutGrid, List, Search, SlidersHorizontal, Star, Upload, X } from 'lucide-react';
import { statusLabels, type Paper } from './data';
import { useApp } from './context';
import { Badge, Empty, IconButton, Modal } from './ui';

export default function Library() {
  const { project, updateProject, openPaper, setPage, notify } = useApp();
  const {data:downloads,error:downloadError,item:downloadItem}=useDownloads(project.id);
  const {data:markdown,error:markdownError}=useMarkdown(project.id);
  const {data:vectors,error:vectorError}=useVectors(project.id);
  const artifact=(id:string)=>{const pmid=id.replace('PMID-','');const indexed=vectors?.items.find(i=>i.pmid===pmid);if(indexed)return indexed;const local=markdown?.items.find(i=>i.pmid===pmid);return local?{pmid,pdfState:local.pdfState,markdownState:local.markdownState,vectorState:'checking',sourceKind:local.pdf?'fulltext':'pubmed_abstract'}:undefined;};
  function artifactLabel(key:'pdfState'|'markdownState'|'vectorState',state:string,abstractOnly:boolean){
   const name=tr({pdfState:'PDF',markdownState:'转换文本',vectorState:'检索材料'}[key]);
   if(state==='latest')return key==='pdfState'?'已有 PDF':key==='markdownState'?'已转换':abstractOnly?'摘要可用于问答':'可用于问答';
   if(state==='outdated')return tr("{p0}需更新",{p0:name});
   if(state==='invalid')return tr("{p0}不可用",{p0:name});
   if(state==='blocked')return key==='markdownState'?'需先下载 PDF':'需先准备原文';
   if(state==='missing')return key==='pdfState'?'待下载':key==='markdownState'?'待转换':'待准备检索';
   return '正在检查';
  }
  const [downloadBusy,setDownloadBusy]=useState(false);
  const [reconvert,setReconvert]=useState(false);const [replaceEdited,setReplaceEdited]=useState(false);
  const conversionBusy=!!markdown?.job&&['queued','running','stopping'].includes(markdown.job.state);
  const hasPdf=(id:string)=>!!downloads.assets[id.replace('PMID-','')]?.exists||!!markdown?.items.find(i=>i.pmid===id.replace('PMID-',''))?.pdf;
  const usesAbstract=(id:string)=>!!markdown?.items.find(i=>i.pmid===id.replace('PMID-',''))?.abstractFallback;
  const sourcePrepared=(id:string)=>{const local=markdown?.items.find(i=>i.pmid===id.replace('PMID-',''));return usesAbstract(id)||!!(local?.ready&&!local.needsCleaning&&!local.needsConversion);};
  const isConverted=(id:string)=>!!markdown?.items.find(i=>i.pmid===id.replace('PMID-',''))?.ready;
  const papers=project.papers.map(p=>({...p,status:hasPdf(p.id)?'pdf' as const:p.researchManaged?(usesAbstract(p.id)?'abstract' as const:downloadItem(p.id.replace('PMID-',''))?.state==='failed'?'failed' as const:['queued','running','paused'].includes(downloadItem(p.id.replace('PMID-',''))?.state||'')?'pending' as const:'abstract' as const):p.status}));
  const eligible=papers.filter(p=>p.researchManaged);
  const activeBatch=downloads.batches.find(b=>['queued','running','paused'].includes(b.state));
  const [tab, setTab] = usePageState(`${project.id}:library:tab`,'all');
  const [query, setQuery] = usePageState(`${project.id}:library:query`,'');
  const [status, setStatus] = usePageState(`${project.id}:library:status`,'all');
  const [sort, setSort] = usePageState(`${project.id}:library:sort`,'added');
  const [grid, setGrid] = usePageState(`${project.id}:library:grid`,false);
  const [selected, setSelected] = usePageState<string[]>(`${project.id}:library:selected`,[]);
  useEffect(()=>{setSelected(ids=>ids.filter(id=>project.papers.some(p=>p.id===id)));},[project.papers]);
  const [detail, setDetail] = useState<Paper | null>(null);
  const filtered = papers.filter(p => (tab !== 'starred' || p.starred) && (tab !== 'fulltext' || (p.status === 'indexed'||p.status === 'pdf')) && (tab !== 'converted' || isConverted(p.id)) && (tab !== 'needs' || (p.researchManaged?!sourcePrepared(p.id):p.status !== 'indexed')) && (status === 'all' || p.status === status) && `${p.title} ${p.author} ${p.tag} ${p.journal}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => sort === 'year' ? b.year - a.year : sort === 'title' ? a.title.localeCompare(b.title) : 0);
  function toggle(id: string) { setSelected(current => current.includes(id) ? current.filter(v => v !== id) : [...current, id]); }
  function star(id: string) { updateProject(p => ({ ...p, papers: p.papers.map(item => item.id === id ? { ...item, starred: !item.starred } : item) })); }
  async function process(ids?: string[]) {
    setDownloadBusy(true);
    try { const chosen=ids?.filter(id=>eligible.some(p=>p.id===id)).map(id=>id.replace('PMID-',''));if(chosen&&!chosen.length)throw new Error('请选择当前纳入的 PubMed 文献');const r=await startDownload(project.id,chosen);notify(tr("已创建 {p0} 篇文献的下载批次",{p0:r.count}));setSelected([]); }
    catch(e){notify(message(e),{tone:'error'});}finally{setDownloadBusy(false);}
  }
  async function convertSelection(force=false) {
    setDownloadBusy(true);
    try { const pmids=selected.filter(id=>hasPdf(id)&&eligible.some(p=>p.id===id)).map(id=>id.replace('PMID-',''));if(!pmids.length)throw new Error('请选择已有 PDF 的当前文献');
      const result=await rpc<{count:number}>('markdown.start',{project:project.id,pmids,force,replaceEdited:force&&replaceEdited});notify(tr("已创建 {p0} 篇转换任务",{p0:result.count}));setReconvert(false);setSelected([]);downloadChanged();
    }catch(e){notify(message(e),{tone:'error'});}finally{setDownloadBusy(false);}
  }
  const tabs=useTabs(tab,['all','starred','fulltext','converted','needs'],value=>{setTab(value);setSelected([]);});
  return <div className="page library-page">
    <div className="page-heading"><div><h1>{tr("文献库")}<span className="heading-count">{papers.length}</span></h1></div><button className="button secondary compact" onClick={()=>setPage('search')}><Upload size={15}/>{tr("添加文献")}</button></div>
    <LiteratureWorkflow vectors={vectors} vectorError={vectorError} downloads={downloads} markdown={markdown} total={eligible.length} error={downloadError||markdownError}/>
    <div className="library-tabs"><div role="tablist" aria-label={tr("文献分类")}>{[['all', '全部文献', papers.length], ['starred', '已收藏', papers.filter(p => p.starred).length], ['fulltext', '已有全文', papers.filter(p => (p.status === 'indexed'||p.status === 'pdf')).length], ['converted', '已转换', papers.filter(p=>isConverted(p.id)).length], ['needs', '待准备', papers.filter(p=>p.researchManaged?!sourcePrepared(p.id):p.status!=='indexed').length]].map(([id, label, count]) => <button {...tabs.tab(String(id))} key={id} className={tab === id?'active':''}>{tr(label)}<span>{count}</span></button>)}</div></div>
    {['all','starred','fulltext','converted','needs'].filter(id=>id!==tab).map(id=><div key={id} {...tabs.panel(id)} hidden/>)}<div {...tabs.panel(tab)}>
    <div className="library-toolbar"><label className="search-field"><Search size={16} /><input aria-label={tr("搜索文献")} placeholder={tr("搜索标题、作者或关键词…")} value={query} onChange={e => setQuery(e.target.value)} />{query && <button aria-label={tr("清空搜索")} onClick={() => setQuery('')}><X size={14} /></button>}</label><div className="toolbar-filters"><label className="select-control"><SlidersHorizontal size={14} /><Select aria-label={tr("文献状态")} value={status} onChange={e => setStatus(e.target.value)}><option value="all">{tr("全部状态")}</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{tr(label)}</option>)}</Select><ChevronDown size={12} /></label><label className="select-control"><ArrowDown size={14} /><Select aria-label={tr("排序方式")} value={sort} onChange={e => setSort(e.target.value)}><option value="added">{tr("添加顺序")}</option><option value="year">{tr("发表年份")}</option><option value="title">{tr("标题排序")}</option></Select><ChevronDown size={12} /></label><div className="view-toggle"><IconButton icon={List} label={tr("列表视图")} active={!grid} onClick={() => setGrid(false)} /><IconButton icon={LayoutGrid} label={tr("卡片视图")} active={grid} onClick={() => setGrid(true)} /></div></div></div>
    {selected.length > 0 && <div className="selection-bar"><span><Check size={15} />{tr("已选择")}{selected.length} {tr("篇文献")}</span><button disabled={downloadBusy||!!activeBatch} onClick={() => void process(selected)}><Download size={14} />{tr("下载选中")}</button><button disabled={downloadBusy||conversionBusy||!markdown?.ready} onClick={()=>void convertSelection()}>{tr("转换选中")}</button><button disabled={downloadBusy||conversionBusy||!markdown?.ready} onClick={()=>{setReplaceEdited(false);setReconvert(true);}}>{tr("重新转换…")}</button><button onClick={() => { updateProject(p => ({ ...p, papers: p.papers.map(v => selected.includes(v.id) ? { ...v, starred: true } : v) })); setSelected([]); notify('已收藏选中文献'); }}><Star size={14} />{tr("收藏")}</button><button onClick={() => setSelected([])}>{tr("取消选择")}</button></div>}
    {filtered.length?<div className={grid ? 'paper-grid' : 'paper-table'}>
      {!grid && <div className="table-header"><input type="checkbox" aria-label={tr("选择当前全部文献")} checked={filtered.length > 0 && filtered.every(p => selected.includes(p.id))} onChange={e => setSelected(e.target.checked ? filtered.map(p => p.id) : [])} /><span>{tr("文献 / 标题")}</span><span>{tr("年份")}</span><span>{tr("处理状态")}</span><span /></div>}
      {filtered.map(paper => <article className={`paper-row ${selected.includes(paper.id) ? 'selected' : ''}`} key={paper.id}><input type="checkbox" aria-label={tr("选择 {p0}",{p0:paper.id})} checked={selected.includes(paper.id)} onChange={() => toggle(paper.id)} /><div className="paper-main"><div className={`paper-icon ${paper.status === 'indexed' ? '' : 'muted'}`}><FileText size={20} strokeWidth={1.4} /></div><div><button className="paper-title" onClick={() => setDetail(paper)}>{paper.title}</button><div className="paper-meta"><span>{paper.author}</span><span className="meta-dot">·</span><span className="journal" title={paper.journal}>{paper.journal}</span><div className="paper-tags">{paper.tag&&paper.tag!=='PubMed'&&<button onClick={() => setQuery(paper.tag)}>{paper.tag}</button>}{!paper.researchManaged&&<span>{tr("本地导入")}</span>}</div></div></div></div><span className="paper-year">{paper.year || '—'}</span><div className="paper-pdf-cell">{paper.researchManaged?<>{artifact(paper.id)?<div className="artifact-tags">{usesAbstract(paper.id)&&<span className="artifact-state" data-state="latest">{tr("仅有摘要")}</span>}{(['pdfState','markdownState','vectorState'] as const).filter(key=>!usesAbstract(paper.id)||key==='vectorState').map(key=><span key={key} className="artifact-state" data-state={artifact(paper.id)![key]}>{tr(artifactLabel(key,artifact(paper.id)![key],artifact(paper.id)?.sourceKind==='pubmed_abstract'))}</span>)}</div>:<PdfStatus asset={downloads.assets[paper.id.replace('PMID-','')]} item={downloadItem(paper.id.replace('PMID-',''))}/>}</>:<Badge paper={paper}/>}</div><IconButton icon={Star} label={`${tr(paper.starred ? '取消收藏' : '收藏')} ${paper.id}`} active={paper.starred} onClick={() => star(paper.id)} /></article>)}
    </div>:<Empty title={papers.length ? tr('没有找到匹配的文献') : tr('新的研究，从第一篇文献开始')} text={papers.length ? tr('试试其他关键词，或清除当前筛选条件。') : tr('通过 PubMed 检索或从 Zotero 集合导入文献。')}><button className="button secondary" onClick={() => { if (papers.length) { setQuery(''); setStatus('all'); setTab('all'); } else setPage('search'); }}>{papers.length ? tr('清除筛选') : tr('添加第一篇文献')}<ArrowRight size={14} /></button></Empty>}
    <div className="table-footer"><span>{tr("共")}{filtered.length} {tr("篇文献")}{query?tr(" · 已应用搜索条件"):''}</span></div>
    </div>
    {reconvert&&<Modal title={tr("重新转换选中文献")} subtitle={tr("重新提取所选 PDF 的内容")} onClose={()=>setReconvert(false)}><div className="detail-body"><p>{tr("重新提取正文和图表。成功后替换当前转换文本，并保留历史副本；失败时保留现有文本。")}</p><label className="wb-check"><input type="checkbox" checked={replaceEdited} onChange={e=>setReplaceEdited(e.target.checked)}/>{tr("也替换手动编辑过的 Markdown（保留历史副本）")}</label><button className="button primary" disabled={downloadBusy} onClick={()=>void convertSelection(true)}>{tr("开始重新转换")}</button></div></Modal>}
    {detail && <Modal title={tr("文献详情")} subtitle={tr("文献信息与全文")} onClose={() => setDetail(null)}><div className="detail-body"><Badge paper={papers.find(p => p.id === detail.id)||detail} /><h2 className="serif">{detail.title}</h2><p className="quiet">{detail.author} · {detail.year||tr("年份未知")}</p><p className="journal">{detail.journal}</p><div className="rule" /><h4>{tr("摘要")}</h4><p className="abstract">{detail.abstract}</p>{detail.researchManaged&&<PdfDetails pmid={detail.id.replace('PMID-','')} asset={downloads.assets[detail.id.replace('PMID-','')]} item={downloadItem(detail.id.replace('PMID-',''))}/>}<div className="detail-footer"><code>{detail.id}</code><button className="button primary" onClick={() => { openPaper(detail); setDetail(null); }}>{tr("阅读与笔记")}<ArrowUpRight size={15} /></button></div></div></Modal>}
  </div>;
}
