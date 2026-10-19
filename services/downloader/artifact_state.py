"""Content fingerprints and per-article lifecycle, independent of file timestamps."""
from file_identity import change_ns
import managed_sqlite
import hashlib,json,sqlite3
import corpus_files as files

def membership(e):
    path=files.base(e)/'metadata/corpus-membership.json'
    return json.loads(path.read_text()) if path.exists() else {'ids':[],'epochs':{},'pending':[]}

def epoch(e,pmid):return membership(e).get('epochs',{}).get(pmid,0)

def file_hash(e,path):
    if not path.is_file():return None
    if path.is_symlink():raise ValueError('文献文件不能是符号链接')
    stat=path.stat();signature=f'{stat.st_size}:{stat.st_mtime_ns}:{change_ns(path,stat)}'
    cache=files.folder(e,'metadata')/'file-fingerprints.sqlite3'
    c=managed_sqlite.connect(cache,timeout=15)
    try:
        c.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,signature TEXT,sha TEXT)')
        key=str(path.relative_to(files.base(e)));old=c.execute('SELECT signature,sha FROM files WHERE path=?',(key,)).fetchone()
        if old and old[0]==signature:return old[1]
        if path.suffix=='.pdf':sha=e.validate_pdf(path)['sha256']
        else:sha=hashlib.sha256(path.read_bytes()).hexdigest()
        after=path.stat()
        if signature!=f'{after.st_size}:{after.st_mtime_ns}:{change_ns(path,after)}':raise ValueError('文件正在变化，请稍后重试')
        c.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)',(key,signature,sha));c.commit();return sha
    finally:c.close()

def markdown_state(e,p,cfg):
    import markdown_service as m
    import conversion_config as conversion
    base=files.base(e);pdf=base/'pdf'/f'{p}.pdf';raw=base/'markdown/raw'/f'{p}.md';md=base/'markdown'/f'{p}.md';meta=base/'metadata/markdown'/f'{p}.json'
    info=json.loads(meta.read_text()) if meta.is_file() else {};error=''
    try:sha=file_hash(e,pdf)
    except ValueError as ex:sha=None;error=str(ex)
    pdf_state='latest' if sha else 'invalid' if pdf.exists() else 'missing'
    raw_hash=file_hash(e,raw);md_hash=file_hash(e,md)
    valid=bool(sha and md_hash and info.get('pdfSha256')==sha and info.get('rebuildEpoch',0)==epoch(e,p))
    # Adopt existing raw files once; future changes are detected by content.
    if valid and raw_hash and 'rawSha256' not in info:
        info['rawSha256']=raw_hash;e.write_json(meta,info)
    target_matches=conversion.matches(e.ROOT,info,cfg)
    # A new engine is only a target: keep the published source usable until its replacement succeeds.
    published_cfg=cfg if target_matches else info.get('conversionConfig',{**m.DEFAULTS,**cfg,'engine':'marker'})
    needs_clean=valid and (not raw_hash or info.get('rawSha256')!=raw_hash or not m.signature_matches(info,published_cfg))
    needs_conversion=bool(sha and (not valid or not target_matches))
    state='latest' if valid and not needs_clean else 'outdated' if md.exists() else 'missing'
    return {'pmid':p,'pdf':bool(sha),'raw':raw.is_file(),'ready':valid,'needsCleaning':bool(needs_clean),'needsConversion':needs_conversion,'engine':info.get('engine','Marker 1.6.0') if valid else '', 'pdfState':pdf_state,'markdownState':state,'pdfSha256':sha,'markdownSha256':md_hash,'rawSha256':raw_hash,'layoutRemoved':info.get('layoutRemoved',0),'removed':info.get('removedCount',0),'error':error or info.get('error','')}


def abstract_fallbacks(e):
    """Only a completed, actually attempted download can settle on an abstract.

    Inspect the latest terminal attempt per article. A cancelled/queued run does
    not erase an earlier result; deleting a successfully downloaded PDF is not
    treated as a download failure.
    """
    import vector_chunks
    articles,_=vector_chunks.xml_articles(e);seen=set();fallbacks=set()
    for row in e.rows("""SELECT i.pmid,i.state,i.paper,b.config,EXISTS(SELECT 1 FROM attempts a WHERE a.batch=i.batch AND a.pmid=i.pmid) AS attempted
        FROM items i JOIN batches b ON b.id=i.batch
        WHERE b.project=? AND i.state IN ('failed','deferred','success','skipped')
        ORDER BY b.created DESC""",(e.PROJECT,)):
        p=row['pmid']
        if row['state'] in ('failed','deferred') and json.loads(row['config']).get('downloadMode')=='zotero':continue
        if p in seen:continue
        seen.add(p);article=articles.get(p,{})
        old=json.loads(row['paper'])
        if row['state'] in ('failed','deferred') and row['attempted'] and article.get('abstract','').strip() and old.get('doi','').lower()==article.get('doi','').lower():fallbacks.add(p)
    return fallbacks


def download_status(e, items):
    """Download freshness is completed coverage, not full-text availability.

    Valid local PDFs always satisfy coverage. Missing PDFs need an actual attempt
    in a completed batch with the same article identifiers and sufficient source
    coverage. Cancelled/paused attempts cannot settle new articles. A missing or
    invalid formerly successful PDF needs acquisition again.
    """
    missing = [i['pmid'] for i in items if not i['pdf']]
    if not missing or (files.base(e)/'metadata/pdf-cleared.json').exists():
        return {'latest': bool(items) and not missing, 'pending': len(missing), 'pendingPmids': missing,
                'attemptedMissing': 0, 'missing': len(missing)}
    import vector_chunks
    articles, _ = vector_chunks.xml_articles(e)
    cfg = e.config()
    latest = {}
    for row in e.rows("""SELECT i.pmid,i.state,i.paper,b.state AS batch_state,b.config,
        EXISTS(SELECT 1 FROM attempts a WHERE a.batch=i.batch AND a.pmid=i.pmid) AS attempted
        FROM items i JOIN batches b ON b.id=i.batch
        WHERE b.project=? AND i.state IN ('failed','deferred','success','skipped')
        ORDER BY b.created DESC""", (e.PROJECT,)):
        # Local-only misses neither settle full-source coverage nor erase a prior full run.
        if row['state'] in ('failed','deferred') and json.loads(row['config']).get('downloadMode')=='zotero':
            continue
        # A later cancelled retry does not erase an earlier completed attempt.
        if row['pmid'] in latest:
            continue
        if row['state'] in ('success', 'skipped') or row['batch_state'] == 'done':
            latest[row['pmid']] = row
    pending = []
    settled_missing = 0
    for item in items:
        if item['pdf']:
            continue
        p = item['pmid']
        row = latest.get(p)
        settled = False
        if item['pdfState'] != 'invalid' and row and row['state'] in ('failed', 'deferred') and row['attempted']:
            old = json.loads(row['paper'])
            previous = {**e.DEFAULTS, **json.loads(row['config'])}
            current = articles.get(p, {})
            same_article = all(str(old.get(k) or '').strip().casefold() == str(current.get(k) or '').strip().casefold()
                               for k in ('doi', 'pmcid'))
            # Newly enabled sources need another pass. Throughput and timeout
            # changes alone leave coverage current; users can explicitly retry.
            sources_covered = all(not cfg.get(k) or previous.get(k) for k in ('fastOa',))
            mirrors_covered = set(cfg.get('mirrors', [])) <= set(previous.get('mirrors', []))
            settled = same_article and sources_covered and mirrors_covered
        if settled:
            settled_missing += 1
        else:
            pending.append(p)
    return {'latest': bool(items) and not pending, 'pending': len(pending), 'pendingPmids': pending,
            'attemptedMissing': settled_missing, 'missing': sum(not i['pdf'] for i in items)}
