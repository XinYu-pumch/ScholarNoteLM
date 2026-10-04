import {useDownloads} from './download-api';
import {PdfDetails,PdfStatus} from './Downloads';
import Select from './Select';
import { useState } from 'react';
import { ArrowLeft, ArrowUpRight, BookOpen, ChevronDown, FileText, MessageSquare, SquarePen } from 'lucide-react';

import { useApp } from './context';
import { Badge, Empty } from './ui';

export function Reader() {
  const { project, paperId, setPage, updateProject, setPaperId } = useApp();
  const {data:downloads,item:downloadItem}=useDownloads(project.id);
  const paper = project.papers.find(p => p.id === paperId) || project.papers[0];
  const [view, setView] = useState('text');
  if (!paper) return <Empty title="还没有可阅读的文献" text="先前往文献库添加文献。"><button className="button primary" onClick={() => setPage('library')}>前往文献库</button></Empty>;
  const pmid=paper.id.replace('PMID-','');const asset=downloads.assets[pmid];
  return <div className="reader-page"><div className="reader-toolbar"><button className="text-button" onClick={() => setPage('library')}><ArrowLeft size={15} />返回文献库</button><label className="reader-select"><Select aria-label="切换阅读文献" value={paper.id} onChange={e => setPaperId(e.target.value)}>{project.papers.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</Select><ChevronDown size={14} /></label>{paper.researchManaged?<PdfStatus asset={asset} item={downloadItem(pmid)}/>:<Badge paper={paper}/>}</div><div className="reader-layout"><div className="reader-document"><div className="reader-tabs"><button className={view === 'text' ? 'active' : ''} onClick={() => setView('text')}><FileText size={15} />摘要</button><button className={view === 'source' ? 'active' : ''} onClick={() => setView('source')}><BookOpen size={15} />来源信息</button></div>{view === 'text' ? <article className="reading-sheet"><span className="eyebrow">PUBMED</span><h1>{paper.title}</h1>{paper.author.length>100?<details className="reader-authors" key={paper.id}><summary>{paper.author.slice(0,90)}… <span>展开作者</span></summary><p>{paper.author}</p></details>:<p className="reader-author">{paper.author}</p>}<div className="reader-publication">{paper.journal} <span>·</span> {paper.year || '年份未提供'}</div><div className="reading-disclaimer">{asset?.exists?'下方为 PubMed 摘要。可在“来源信息”中打开已下载的 PDF。':'下方为 PubMed 摘要，可下载全文，或从 Zotero 导入 PDF。'}</div><h2>Abstract <span>摘要</span></h2><p>{paper.abstract}</p><div className="reading-footer">{paper.id}<span>PubMed 文献信息</span></div></article> : <div className="source-info"><h2>来源信息</h2><dl><dt>标识</dt><dd>{paper.id}</dd><dt>内容类型</dt><dd>PubMed 文献</dd><dt>全文文件</dt><dd>{asset?.exists?'已下载 PDF':'尚未关联 PDF'}</dd></dl>{paper.researchManaged&&<PdfDetails pmid={pmid} asset={asset} item={downloadItem(pmid)}/>}<p>PDF 使用系统阅读器打开。文献准备状态可在文献库查看。</p></div>}</div><aside className="notes-panel"><div className="panel-heading"><h3><SquarePen size={16} />阅读笔记</h3><span className="subtle-badge">自动保存</span></div><p className="panel-description">记录发现，也记录疑问。</p><textarea aria-label="阅读笔记" placeholder={"这篇文献带给你哪些启发？\n\n• 研究问题\n• 方法与发现\n• 局限与思考"} value={project.notes[paper.id] || ''} onChange={e => updateProject(p => ({ ...p, notes: { ...p.notes, [paper.id]: e.target.value } }))} /><div className="notes-bottom"><BookOpen size={17} /><p>笔记属于当前项目，独立于文献原文保存。</p></div><button className="button secondary" onClick={() => setPage('chat')}><MessageSquare size={15} />向项目文献提问<ArrowUpRight size={14} /></button></aside></div></div>;
}
