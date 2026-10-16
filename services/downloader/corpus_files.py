"""Reconcile materialized article files against the current PubMed corpus."""
import hashlib,json,os,re,time,shutil
from pathlib import Path
from contextlib import contextmanager
import xml.etree.ElementTree as ET
import pubmed_xml
import storage

FAMILIES=(('pdf','.pdf'),)

def base(e):return storage.project_dir(e.ROOT,e.PROJECT)

@contextmanager
def lock(e):
    # UI polling and publishing can overlap. These sections contain local I/O
    # only; wait briefly rather than reporting normal contention as a failure.
    deadline=time.monotonic()+10
    while True:
        guard=storage.file_lock(base(e)/'metadata/article-files.lock')
        try:
            guard.__enter__();break
        except ValueError:
            if time.monotonic()>=deadline:raise
            time.sleep(.05)
    try:yield
    finally:guard.__exit__(None,None,None)

def current(e):
    path=base(e)/'pubmed/current.xml'
    if not path.exists():return None
    root=ET.fromstring(path.read_bytes())
    if root.tag!='PubmedArticleSet':raise ValueError('当前 XML 不是 PubMed 文献集合，未移动任何文件')
    return {e.pmid(c.findtext('PMID')) for _,c,_,_ in pubmed_xml.records(root) if c.findtext('PMID')}

def folder(e,name):
    path=base(e)
    for part in Path(name).parts:
        path=path/part
        if path.is_symlink():raise ValueError('文献目录不能是符号链接')
    path.mkdir(parents=True,exist_ok=True)
    return path

def move(e,src,dest,events):
    if src.is_symlink() or dest.is_symlink():raise ValueError('文献文件不能是符号链接')
    if dest.exists():
        # Keep both versions. Never silently overwrite a user's conflicting file.
        digest=hashlib.sha256(src.read_bytes()).hexdigest()[:16] if src.is_file() else 'directory'
        dest=folder(e,str(dest.parent.relative_to(base(e))/'conflicts'))/f'{src.stem}-{digest}-{time.time_ns()}{src.suffix}'
    dest.parent.mkdir(parents=True,exist_ok=True)
    os.replace(src,dest)
    events.append({'from':str(src.relative_to(base(e))),'to':str(dest.relative_to(base(e)))})

def reconcile(e):
    with lock(e):return reconcile_locked(e)

def delete_derived(e,pmids):
    import vector_chunks
    removed=[]
    for p in pmids:
        e.pmid(p)
        paths=[base(e)/name/f'{p}{ext}' for name,ext in [('markdown','.md'),('markdown/raw','.md'),('abstracts','.md'),('metadata/markdown','.json')]]
        paths += [base(e)/name/p for name in ('markdown/assets','markdown/history')]
        for path in paths:
            # Check every parent before recursive removal; never follow links outside the project.
            for parent in [path,*path.parents]:
                if parent==base(e):break
                if parent.is_symlink():raise ValueError('文献文件不能是符号链接')
            if path.is_dir():shutil.rmtree(path);removed.append(str(path.relative_to(base(e))))
            elif path.exists():path.unlink();removed.append(str(path.relative_to(base(e))))
    vector_chunks.purge_documents(e,pmids)
    return removed

def reconcile_locked(e):
    ids=current(e);events=[];errors=[];restored=0;archived=0
    if ids is None:return {'restored':0,'archived':0,'redundant':0,'errors':[],'missingXml':True}
    import artifact_state
    state=artifact_state.membership(e);known=set(state['ids']);on_disk=set()
    for family,ext in [('pdf','.pdf'),('markdown','.md'),('markdown/raw','.md'),('abstracts','.md'),('metadata/markdown','.json')]:
        for path in folder(e,family).glob('*'+ext):
            if path.stem.isdigit():on_disk.add(path.stem)
    for name in ('markdown/assets','markdown/history'):
        on_disk.update(p.name for p in folder(e,name).iterdir() if p.name.isdigit())
    import vector_chunks
    known.update(vector_chunks.known_pmids(e))
    restored_ids=set();restore_allowed=not (base(e)/'metadata/pdf-cleared.json').exists()
    for path in folder(e,'pdf/redundant').glob('*.pdf'):
        if not restore_allowed or path.stem not in ids or (base(e)/'pdf'/path.name).exists():continue
        if path.is_symlink():raise ValueError('文献文件不能是符号链接')
        try:e.validate_pdf(path);restored_ids.add(path.stem)
        except ValueError:pass
    invalidated=(known|on_disk)-ids | restored_ids | set(state.get('pending',[]))
    import markdown_archive
    archived_markdown=0
    for p in sorted(invalidated-ids):
        previous=state.get('epochs',{}).get(p,0)-(1 if p in state.get('pending',[]) else 0)
        archived_markdown+=markdown_archive.archive(e,p,previous)
    epochs=state.get('epochs',{})
    for p in invalidated-set(state.get('pending',[])):epochs[p]=epochs.get(p,0)+1
    updated={'ids':sorted(ids),'epochs':epochs,'pending':sorted(invalidated)}
    if updated!=state:e.write_json(base(e)/'metadata/corpus-membership.json',updated)
    # No-abstract exclusions retire current evidence, but retain existing material
    # in a separate archive before the normal membership cleanup removes derivatives.
    exclusions=base(e)/'metadata/abstract-exclusions.json'
    excluded={str(x['pmid']) for x in json.loads(exclusions.read_text())} if exclusions.exists() else set()
    for p in invalidated & excluded:
        archive=base(e)/'archive/without-abstract'/p
        if not (archive/'exclusion.json').exists():
            e.write_json(archive/'exclusion.json',{'pmid':p,'reason':'XML 无有效摘要','retired':time.time()})
        for name in ('markdown','markdown/raw','abstracts','metadata/markdown'):
            source=base(e)/name/(p+('.json' if name=='metadata/markdown' else '.md'))
            if source.is_file():
                dest=archive/name/source.name;dest.parent.mkdir(parents=True,exist_ok=True)
                if not dest.exists():shutil.copy2(source,dest)
        for name in ('markdown/assets','markdown/history'):
            source=base(e)/name/p;dest=archive/name/p
            if source.is_dir() and not dest.exists():shutil.copytree(source,dest,symlinks=True)
    deleted=delete_derived(e,invalidated) if invalidated else []
    updated['pending']=[]
    if invalidated:e.write_json(base(e)/'metadata/corpus-membership.json',updated)
    for family,ext in FAMILIES:
        active=folder(e,family);spare=folder(e,family+'/redundant')
        for src in active.glob('*'+ext):
            if not re.fullmatch(r'\d{1,12}',src.stem) or src.stem in ids:continue
            move(e,src,spare/src.name,events)
            if family=='pdf':archived+=1
        for src in spare.glob('*'+ext):
            p=src.stem
            if not restore_allowed or p not in ids or not re.fullmatch(r'\d{1,12}',p):continue
            dest=active/src.name
            if src.is_symlink() or dest.is_symlink():raise ValueError('文献文件不能是符号链接')
            if dest.exists():continue
            if family=='pdf':
                try:e.validate_pdf(src)
                except Exception as exc:errors.append({'pmid':p,'error':str(exc)});continue
            move(e,src,dest,events)
            if family=='pdf':restored+=1
    restored_markdown=sum(markdown_archive.restore(e,p) for p in sorted(ids))
    for row in e.rows('SELECT pmid,data FROM assets WHERE project=?',(e.PROJECT,)):
        info=json.loads(row['data']);p=row['pmid'];is_archived=p not in ids
        if info.get('archived')==is_archived and info.get('path')==f"pdf/{'redundant/' if is_archived else ''}{p}.pdf":continue
        info.update(archived=is_archived,path=f"pdf/{'redundant/' if is_archived else ''}{p}.pdf")
        e.execute('UPDATE assets SET data=? WHERE project=? AND pmid=?',(json.dumps(info,ensure_ascii=False),e.PROJECT,p))
    for event in events:
        path=Path(event['to'])
        if path.parent==Path('pdf'):
            p=path.stem;old=e.rows('SELECT data FROM assets WHERE project=? AND pmid=?',(e.PROJECT,p))
            previous=json.loads(old[0]['data']) if old else {};checked=e.validate_pdf(base(e)/path)
            # A replacement in the backup folder must not inherit the old PDF's origin.
            previous=previous if previous.get('sha256')==checked['sha256'] else {}
            info={**previous,**checked,'pmid':p,'path':str(path),'archived':False,'restored':time.time()}
            info.setdefault('source','冗余目录恢复')
            e.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(e.PROJECT,p,json.dumps(info,ensure_ascii=False)))
    result={'restored':restored,'archived':archived,'redundant':len(list(folder(e,'pdf/redundant').glob('*.pdf'))),'errors':errors,'deletedDerived':len(deleted),'archivedMarkdown':archived_markdown,'restoredMarkdown':restored_markdown}
    if events or deleted or restored_markdown:e.write_json(base(e)/'logs'/f'corpus-files-{time.time_ns()}.json',{'time':time.time(),**result,'moves':events,'deleted':deleted})
    return result


def register_local_pdfs(e):
    """Refresh user-supplied PMID PDFs without triggering downloads or conversion."""
    import artifact_state
    registered=0;invalid=[]
    for p in sorted(current(e) or set()):
        path=base(e)/'pdf'/f'{p}.pdf'
        if not path.exists():continue
        try:sha=artifact_state.file_hash(e,path)
        except ValueError as ex:invalid.append({'pmid':p,'error':str(ex)});continue
        old=e.rows('SELECT data FROM assets WHERE project=? AND pmid=?',(e.PROJECT,p))
        info=json.loads(old[0]['data']) if old else {}
        if info.get('sha256')==sha and not info.get('archived'):continue
        info={**e.validate_pdf(path),'pmid':p,'path':f'pdf/{p}.pdf','source':'用户提供的 PDF','archived':False,'updated':time.time()}
        e.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(e.PROJECT,p,json.dumps(info,ensure_ascii=False)));registered+=1
    return {'registered':registered,'invalid':invalid}


def update_missing_pdf_report(e):
    with lock(e):return update_missing_pdf_report_locked(e)

def update_missing_pdf_report_locked(e):
    """Refresh current-corpus missing-PDF and source reports from one snapshot.

    Caller holds the article-files lock, keeping application PDF publication,
    reconciliation and this atomic snapshot consistent.
    """
    import artifact_state
    ids=current(e)
    if ids is None:return {'missingXml':True}
    directory=folder(e,'pdf');missing=[];available={}
    for p in sorted(ids,key=int):
        try:sha=artifact_state.file_hash(e,directory/f'{p}.pdf')
        except ValueError:sha=None
        if sha:available[p]=sha
        else:missing.append(p)
    dest=base(e)/'literature_without_pdf.txt'
    e.atomic(dest,''.join(p+'\n' for p in missing))
    sources=write_pdf_sources_report_locked(e,available)
    return {'missingPdfCount':len(missing),'missingPdfReport':str(dest),**sources}


def write_pdf_sources_report_locked(e,available):
    """Use only provenance belonging to the current validated bytes; no new PDF parsing."""
    from collections import Counter
    assets={}
    for row in e.rows('SELECT pmid,data FROM assets WHERE project=?',(e.PROJECT,)):
        try:info=json.loads(row['data'])
        except (ValueError,TypeError):continue
        if isinstance(info,dict):assets[row['pmid']]=info
    entries=[]
    for p,sha in available.items():
        info=assets.get(p,{})
        source=' '.join(str(info.get('source') or '').split()) if info.get('sha256')==sha else ''
        if source in ('已有本地 PDF','冗余目录恢复'):
            source+='（原始来源未知）'
        entries.append((p,f'pdf/{p}.pdf',source or '未知（无匹配的来源记录）'))
    counts=Counter(row[2] for row in entries)
    lines=['ScholarNoteLM PDF 来源报告',f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S %z')}",
           '范围：当前 XML 文献集合中的有效 PDF；不含冗余备份、损坏或缺失文件。',
           f'有效 PDF 总数：{len(entries)}','', '来源统计','来源\t数量']
    lines.extend(f'{source}\t{counts[source]}' for source in sorted(counts))
    if not entries:lines.append('当前没有有效 PDF。')
    lines+=['','逐篇来源（按 PMID 数值排序）','PMID\tPDF 文件\t来源']
    lines.extend('\t'.join(row) for row in entries)
    dest=base(e)/'literature_pdf_sources.txt'
    e.atomic(dest,'\n'.join(lines)+'\n')
    return {'pdfSourcesCount':len(entries),'pdfSourcesReport':str(dest)}
