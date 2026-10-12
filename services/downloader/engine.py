"""Durable, project-local PDF download service. JSON RPC on stdin; --worker for jobs."""
from __future__ import annotations
import compact_io
import asyncio, base64, hashlib, json, os, random, re, sqlite3, struct, subprocess, sys, time, uuid, zipfile
from collections import Counter
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote, unquote
import xml.etree.ElementTree as ET
import pubmed_xml
import storage
import corpus_files
import scihub_retry
import pmc_parallel
import europe_pmc_pdf
# Status/settings RPCs stay lightweight; network/PDF modules load only for real work.
def load_sources():
    global httpx, badr
    if 'httpx' not in globals():
        import httpx
        import badr_sources as badr


ROOT = Path(os.environ.get('SCHOLARNOTELM_ROOT', Path(__file__).resolve().parents[2])).resolve()
PROJECT = 'p'
S3 = 'https://pmc-oa-opendata.s3.amazonaws.com'
STAGES = ['pmc_s3', 'europe_pmc_getpdf', 'scihub_bloom', 'unpaywall', 'scihub_retry', 'zotero']
LABELS = dict(zip(STAGES, ['PMC S3', 'Europe PMC getPdf', 'Sci-Hub 首轮 / 来源缓存', 'Unpaywall', 'Sci-Hub 补救 / 重试', 'Zotero 本地补充']))
SCI_HUB_BROWSER = ContextVar('scihub_browser_pool',default=None)
HTTP_TRACE = ContextVar('download_http_trace', default=None)
DB_TIMEOUT = ContextVar('download_db_timeout', default=15)
DEFAULTS = {'zoteroAddress':'localhost:23119', 'email':'', 'fastOa':True, 'unpaywallConcurrency':10,
 'pmcConcurrency':5, 'europePmcConcurrency':4, 'europePmcTimeout':60, 'europePmcAttempts':3, 'timeout':20, 'attempts':3, 'oaFileTimeout':45, 'oaArticleTimeout':60, 's3ArticleTimeout':60,
 'mirrors':['https://sci-hub.ru','https://sci-hub.su','https://sci-hub.st','https://sci-hub.red','https://sci-hub.box']}
BUILTIN_BLOOM = 'data/reference/download/scihub.bloom'

def db(system=False):
    path=ROOT/'data/research/downloads.sqlite3' if system else storage.project_dir(ROOT,PROJECT)/'metadata/downloads.sqlite3'; path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=DB_TIMEOUT.get()); c.row_factory=sqlite3.Row
    c.executescript('''PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,project TEXT NOT NULL,created REAL NOT NULL,state TEXT NOT NULL,control TEXT NOT NULL DEFAULT '',snapshot TEXT NOT NULL,config TEXT NOT NULL,owner INTEGER NOT NULL DEFAULT 0,elapsed REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS items(batch TEXT NOT NULL,pmid TEXT NOT NULL,paper TEXT NOT NULL,state TEXT NOT NULL,stage TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',bytes INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(batch,pmid));
    CREATE TABLE IF NOT EXISTS assets(project TEXT NOT NULL,pmid TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(project,pmid));
    CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,batch TEXT NOT NULL,pmid TEXT NOT NULL,stage TEXT NOT NULL,outcome TEXT NOT NULL,elapsed REAL NOT NULL,detail TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS item_progress(batch TEXT NOT NULL,pmid TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(batch,pmid));
    CREATE TABLE IF NOT EXISTS mirror_health(batch TEXT NOT NULL,endpoint TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(batch,endpoint));
    CREATE TABLE IF NOT EXISTS source_cache(pmid TEXT NOT NULL,doi TEXT NOT NULL,kind TEXT NOT NULL,url TEXT NOT NULL,sha256 TEXT NOT NULL DEFAULT '',updated REAL NOT NULL,PRIMARY KEY(pmid,doi,kind,url));
    CREATE TABLE IF NOT EXISTS stage_runs(id INTEGER PRIMARY KEY,batch TEXT NOT NULL,stage TEXT NOT NULL,started REAL NOT NULL,elapsed REAL NOT NULL DEFAULT 0,state TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS batch_project ON batches(project,created);
    ''');return c

def execute(sql,args=()):
    with db() as c:return c.execute(sql,args).rowcount

def rows(sql,args=()):
    with db() as c:return [dict(x) for x in c.execute(sql,args)]

def one(sql,args=()):
    r=rows(sql,args)
    if not r:raise ValueError('下载记录不存在')
    return r[0]

def progress(batch,p):
    r=rows('SELECT data FROM item_progress WHERE batch=? AND pmid=?',(batch,p))
    return json.loads(r[0]['data']) if r else {}

def save_progress(batch,p,value):
    execute('INSERT OR REPLACE INTO item_progress VALUES(?,?,?)',(batch,p,json.dumps(value,ensure_ascii=False)))

def remember_sources(paper, info):
    """Project metadata survives PDF clearing; never reuse across PMID/DOI pairs."""
    doi = str(paper.get('doi') or '').strip().lower()
    if not doi or info.get('source') not in ('Sci-Hub', 'Sci-Net'):
        return
    for kind, url in [('file', info.get('fileUrl') if 'fileUrl' in info else info.get('url')), ('page', info.get('pageUrl'))]:
        if not url:
            continue
        u = urlparse(url)
        if u.scheme not in ('https', 'http') or not u.hostname or u.username or u.password or u.query:
            continue
        execute("INSERT INTO source_cache VALUES(?,?,?,?,?,?) ON CONFLICT(pmid,doi,kind,url) DO UPDATE SET sha256=CASE WHEN excluded.sha256!='' THEN excluded.sha256 ELSE source_cache.sha256 END,updated=excluded.updated",
                (paper['pmid'], doi, kind, url.split('#')[0], info.get('sha256', '') if kind == 'file' else '', info.get('downloaded') or time.time()))

def cached_sources(paper):
    result = rows("SELECT kind,url,sha256 FROM source_cache WHERE pmid=? AND doi=? ORDER BY (sha256!='') DESC,updated DESC",
                  (paper['pmid'], str(paper.get('doi') or '').strip().lower()))
    return ([r for r in result if r['kind'] == 'file'][:2], [r['url'] for r in result if r['kind'] == 'page'][:1])

def bloom_summary(items,attempts,states):
    hit={p for p,v in states.items() if v.get('bloomHit')}
    hit.update(a['pmid'] for a in attempts if 'bloomHit' not in states.get(a['pmid'],{}) and a['stage']=='scihub_bloom' and a['outcome'] in ('failed','success'))
    first={a['pmid'] for a in attempts if a['stage']=='scihub_bloom' and a['outcome']=='success'} & hit
    retry={a['pmid'] for a in attempts if a['stage']=='scihub_retry' and a['outcome']=='success'} & hit - first
    recovered={i['pmid'] for i in items if i['pmid'] in hit-first-retry and i['state'] in ('success','skipped')}
    return {'hits':len(hit),'firstSuccess':len(first),'retrySuccess':len(retry),'otherRecovery':len(recovered),
            'failed':sum(i['pmid'] in hit and i['state']=='failed' for i in items),
            'deferred':sum(i['pmid'] in hit and i['state']=='deferred' for i in items),
            'pending':sum(i['pmid'] in hit and i['state'] not in ('success','skipped','failed','deferred') for i in items)}

def ident(v):
    if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',v):raise ValueError('无效标识')
    return v

def pmid(v):
    v=str(v).removeprefix('PMID-')
    if not re.fullmatch(r'[0-9]{1,12}',v):raise ValueError('需要真实 PubMed PMID')
    return v

def atomic(path,content):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with tmp.open('wb') as f:
        f.write(content if isinstance(content,bytes) else content.encode());f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def write_json(path,value):atomic(path,json.dumps(value,ensure_ascii=False,indent=2))
def batch_dir(b):return storage.project_dir(ROOT,b['project'])/'logs'/ident(b['id'])
def paper_dir(project,p):return storage.project_dir(ROOT,project)/'pdf'
def abstract_path(project,p):return storage.project_dir(ROOT,project)/'abstracts'/f'{pmid(p)}.md'
def asset_path(project,asset):
    # Asset paths are relative to the project, so moving the workspace keeps references intact.
    path=storage.project_dir(ROOT,project)/'pdf'/f'{pmid(asset["pmid"])}.pdf'
    if path.is_symlink():raise ValueError('PDF 不能是符号链接')
    return path
def metadata_path(project,p):return storage.project_dir(ROOT,project)/'metadata/downloads'/f'{pmid(p)}.json'

def config():
    with db(system=True) as c:r=c.execute("SELECT data FROM settings WHERE key='config'").fetchall()
    return {**DEFAULTS,**{k:v for k,v in (json.loads(r[0]['data']) if r else {}).items() if k in DEFAULTS}}

def bloom_info(path):
    path=Path(path)
    with path.open('rb') as f:
        if f.read(8)!=b'OPDRBF1\n':raise ValueError('不是 BADR Bloom 索引')
        size=struct.unpack('>I',f.read(4))[0]
        if not 1<=size<=1_000_000:raise ValueError('索引头长度无效')
        h=json.loads(f.read(size));bits=h.get('bit_count');count=h.get('hash_count')
        if not isinstance(bits,int) or bits<=0 or not isinstance(count,int) or not 1<=count<=128:raise ValueError('索引参数无效')
        if path.stat().st_size != 12+size+(bits+7)//8:raise ValueError('索引长度与头信息不一致')
    return {'valid':True,'bytes':path.stat().st_size,'header':h}

def get_settings():return config()

def save_settings(a):
    cfg=config()
    if 'zoteroAddress' in a:
        from zotero_local import api_address
        value=str(a['zoteroAddress']).strip();api_address(value)
        cfg['zoteroAddress']=value
    for k in ['fastOa']:
        if k in a:
            if not isinstance(a[k],bool):raise ValueError('开关值无效')
            cfg[k]=a[k]
    if 'email' in a:
        v=str(a['email']).strip()
        if v and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v):raise ValueError('联系邮箱格式无效')
        cfg['email']=v
    for k,lo,hi in [('unpaywallConcurrency',1,30),('pmcConcurrency',1,10),('europePmcConcurrency',1,4),('europePmcTimeout',5,300),('europePmcAttempts',1,3),('timeout',5,180),('attempts',1,5),('oaFileTimeout',5,300),('oaArticleTimeout',5,600),('s3ArticleTimeout',5,300)]:
        if k in a:
            n=a[k]
            if isinstance(n,bool) or not isinstance(n,int) or not lo<=n<=hi:raise ValueError(f'{k} 超出范围 {lo}–{hi}')
            cfg[k]=n
    if 'mirrors' in a:
        if not isinstance(a['mirrors'],list) or len(a['mirrors'])>10:raise ValueError('镜像最多 10 个')
        mirrors=[]
        for v in a['mirrors']:
            u=urlparse(v.strip())
            if u.scheme not in ('https','http') or not u.netloc or u.username or u.password:raise ValueError('镜像地址必须是 HTTP(S) 地址')
            mirrors.append(v.strip().rstrip('/'))
        cfg['mirrors']=list(dict.fromkeys(mirrors))
    with db(system=True) as c:c.execute("INSERT OR REPLACE INTO settings VALUES('config',?)",(json.dumps(cfg),))
    return get_settings()

def validate_pdf(path,expected_md5=None):
    from pypdf import PdfReader
    path=Path(path)
    if not path.is_file():raise ValueError('PDF 文件不存在')
    with path.open('rb') as f:
        if b'%PDF-' not in f.read(1024):raise ValueError('响应不是 PDF（可能是网页或错误页）')
    from pypdf.errors import PyPdfError
    try:
        reader=PdfReader(str(path),strict=False)
        if reader.is_encrypted and not reader.decrypt(''):raise ValueError('PDF 已加密，无法读取')
        if len(reader.pages)<1:raise ValueError('PDF 没有可读取的页面')
    except (PyPdfError,KeyError,TypeError) as ex:raise ValueError('PDF 结构无效，无法读取') from ex
    sha=hashlib.sha256();md5=hashlib.md5()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):sha.update(chunk);md5.update(chunk)
    if expected_md5 and md5.hexdigest()!=expected_md5.lower():raise ValueError('PDF MD5 校验不一致')
    return {'bytes':path.stat().st_size,'pages':len(reader.pages),'sha256':sha.hexdigest(),'md5':md5.hexdigest()}

def event(b,p,stage,message,**extra):
    record={'time':time.time(),'pmid':p,'stage':stage,'message':message,**extra}
    path=batch_dir(b)/'download_events.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')

def report(b):
    items=rows('SELECT * FROM items WHERE batch=?',(b['id'],)); counts=Counter(i['state'] for i in items)
    attempts=rows('SELECT * FROM attempts WHERE batch=? ORDER BY id',(b['id'],));cfg=json.loads(b['config'])
    stages=[]
    stage_runs=rows('SELECT * FROM stage_runs WHERE batch=? ORDER BY id',(b['id'],))
    for stage in STAGES:
        a=[{**r,'detail':json.loads(r['detail'])} for r in attempts if r['stage']==stage]
        runs=[r for r in stage_runs if r['stage']==stage]
        measured=bool(a) and all('entryRequests' in r['detail'] for r in a)
        stages.append({'stage':stage,'name':LABELS[stage],
            'attempted':sum(r['outcome']!='skipped' and (not measured or r['detail'].get('entryRequests',0)+r['detail'].get('fileRequests',0)>0) for r in a),
            'deferred':sum(r['outcome']=='deferred' for r in a),
            'entryRequests':sum(r['detail'].get('entryRequests',0) for r in a) if measured else None,
            'fileRequests':sum(r['detail'].get('fileRequests',0) for r in a) if measured else None,
            'success':sum(r['outcome']=='success' for r in a),'failed':sum(r['outcome']=='failed' for r in a),
            'skipped':sum(r['outcome']=='skipped' for r in a),
            'wallSeconds':round(sum(r['elapsed'] for r in runs),3) if runs else None,
            'articleSeconds':round(sum(r['elapsed'] for r in a),3),
            'requestSeconds':round(sum(r['detail'].get('timings',{}).get('lookupSeconds',0)+r['detail'].get('timings',{}).get('downloadSeconds',0) for r in a),3) if measured else None,
            's3PdfFound':len({r['pmid'] for r in a if r['detail'].get('s3PdfFound')}) if stage=='pmc_s3' else None})
    parallel_wall=round(sum(r['elapsed'] for r in stage_runs if r['stage']=='pmc_parallel'),3)
    states={r['pmid']:json.loads(r['data']) for r in rows('SELECT pmid,data FROM item_progress WHERE batch=?',(b['id'],))}
    health={r['endpoint']:json.loads(r['data']) for r in rows('SELECT endpoint,data FROM mirror_health WHERE batch=?',(b['id'],))}
    summary=bloom_summary(items,attempts,states)
    data={**{k:b[k] for k in ['id','project','snapshot','created','state','elapsed','error']},'generated':time.time(),'total':len(items),'counts':dict(counts),'config':cfg,'stages':stages,'stageRuns':stage_runs,'pmcParallelWallSeconds':parallel_wall,'bloomSummary':summary,'mirrorHealth':health,'attempts':[{**a,'detail':json.loads(a['detail'])} for a in attempts],'items':[{**i,'paper':json.loads(i['paper']),'progress':states.get(i['pmid'],{})} for i in items]}
    lines=['ScholarNoteLM Download Report',f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",f"Project: {b['project']}",f"Batch: {b['id']}",f"Corpus snapshot: {b['snapshot']}",f"State: {b['state']}",'','Overall',f'- Total articles: {len(items)}',f"- Newly downloaded: {counts['success']}",f"- Existing PDFs reused: {counts['skipped']}",f"- Final failed: {counts['failed']}",f"- Deferred (not completed): {counts['deferred']}",f"- Unfinished: {sum(counts[s] for s in ['queued','running','paused','cancelled'])}",f"- Active elapsed: {b['elapsed']:.1f}s",'','Strategy',f"- Unpaywall concurrency: {cfg['unpaywallConcurrency']}",f"- PMC concurrency: {cfg['pmcConcurrency']}",f"- HTTP timeout: {cfg['timeout']}s; S3 max attempts: {cfg['attempts']}",f"- Sci-Hub mirrors: {', '.join(cfg['mirrors'])}",'','Stage Summary (wall time vs concurrent article / HTTP time; None = not recorded)']
    lines.extend([f"- PMC S3 + Europe PMC getPdf parallel wall time: {parallel_wall}s (overlapping source times must not be added)",f"- getPdf concurrency: {cfg.get('europePmcConcurrency',4)}; request cap: {cfg.get('europePmcTimeout',60)}s; max attempts: {cfg.get('europePmcAttempts',3)}"])
    for st in stages:
        lines.extend([st['name'],f"- Attempted: {st['attempted']}; Success: {st['success']}; Failed: {st['failed']}; Deferred: {st['deferred']}; Entry HTTP requests: {st['entryRequests']}; File HTTP requests: {st['fileRequests']}; Skipped: {st['skipped']}",
                      f"- Stage wall time: {st['wallSeconds']}s; Concurrent article time sum: {st['articleSeconds']}s; HTTP time sum: {st['requestSeconds']}s"])
        if st['stage']=='pmc_s3':lines.append(f"- Articles with official PDF located: {st['s3PdfFound']}; Download success: {st['success']}")
    hit_pmids={p for p,v in states.items() if v.get('bloomHit')}
    sci_success={a['pmid'] for a in attempts if a['stage'].startswith('scihub') and a['outcome']=='success'}
    data['sourceCacheSuccess']=sum(a['outcome']=='success' and json.loads(a['detail']).get('route') in ('known-file','known-page','known-page-file') for a in attempts)
    lines.append(f"- Historical source cache successes: {data['sourceCacheSuccess']}")
    data['scihubSuccessByBloom']={'hit':len(sci_success & hit_pmids),'nonHit':len(sci_success-hit_pmids)}
    lines.extend(['',f"Sci-Hub success by Bloom: hit={len(sci_success & hit_pmids)}, non-hit / unavailable={len(sci_success-hit_pmids)}"])
    lines+=['','Bloom Recovery Summary',f"- Bloom hits: {summary['hits']}",f"- First Sci-Hub success: {summary['firstSuccess']}",f"- Other source / existing PDF recovery: {summary['otherRecovery']}",f"- Supplemental Sci-Hub success: {summary['retrySuccess']}",f"- Still failed: {summary['failed']}; Deferred: {summary['deferred']}; Pending: {summary['pending']}",
            '- Sci-Hub: fixed workers; one request per mirror entry at a time; each mirror once per article per pass; 75s HTTP + 30s lock wait; entry <=12s, file <=30s; two file requests per origin; cached sources before Bloom gate; unavailable mirrors deferred without sleeping',
            f"- OA file / article budgets: {cfg.get('oaFileTimeout',45)}s / {cfg.get('oaArticleTimeout',60)}s; S3 article budget: {cfg.get('s3ArticleTimeout',60)}s",
            '- Timings include queue/cooldown; they are not pure download speeds.', '', 'Mirror Health',json.dumps(health,ensure_ascii=False,indent=2),'','Article Results']
    for i in items:
        assets=rows('SELECT data FROM assets WHERE project=? AND pmid=?',(b['project'],i['pmid']))
        lines.append(f"PMID {i['pmid']} | {i['state']} | {i['source']} | {i['error']}")
        if i['pmid'] in states:lines.append('Progress: '+json.dumps(states[i['pmid']],ensure_ascii=False))
        if assets:
            asset=json.loads(assets[0]['data']);lines.append(json.dumps({k:v for k,v in asset.items() if k not in ['metadata','profile']},ensure_ascii=False))
    lines+=['','Attempt Details (seconds; requests have separate entry/file roles)']
    for a in attempts:
        lines.append(f"PMID {a['pmid']} | {a['stage']} | {a['outcome']} | {a['elapsed']:.3f}s | {a['detail']}")
    if b['error']:lines+=['','Batch error: '+b['error']]
    d=batch_dir(b);compact_io.write_json(sys.modules[__name__],d/'download_report.json',data);compact_io.write_text(sys.modules[__name__],d/'download_report.txt','\n'.join(lines)+'\n')
    atomic(d/'literature_without_pdf.txt',''.join(i['pmid']+'\n' for i in items if i['state'] in ('failed','deferred')))
    return data

def launch():
    log=ROOT/'logs/downloader.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('ab') as out:
        kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NO_WINDOW}
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker','--project',PROJECT],cwd=ROOT,env=os.environ.copy(),stdin=subprocess.DEVNULL,stdout=out,stderr=out,**kwargs)

def recover():
    # OS lock determines worker liveness; never classify an active network wait as a crash.
    lock=worker_lock()
    if lock is None:return False
    try:
        for b in rows("SELECT * FROM batches WHERE state='running'"):
            state='cancelled' if b['control']=='cancel' else 'paused'
            execute('UPDATE batches SET state=?,control=\'\',error=? WHERE id=?',(state,'下载进程已中断，可继续处理',b['id']))
            execute("UPDATE items SET state=? WHERE batch=? AND state IN ('running','queued')",(state,b['id']))
            report(one('SELECT * FROM batches WHERE id=?',(b['id'],)))
    finally:lock.close()
    return True

def create(a):
    project=ident(a['project']); papers=a.get('papers',[])
    if not papers:raise ValueError('没有可下载的 PubMed 文献')
    recover()
    if a.get('mode')!='zotero':
        (corpus_files.base(sys.modules[__name__])/'metadata/pdf-cleared.json').unlink(missing_ok=True)
    corpus_files.reconcile(sys.modules[__name__])
    if a.get('mode')=='bloom_retry':
        # Rust supplies the current included corpus, not the historical batch corpus.
        eligible={r['pmid'] for r in rows("SELECT a.pmid,p.data FROM attempts a LEFT JOIN item_progress p ON p.batch=a.batch AND p.pmid=a.pmid WHERE a.stage='scihub_bloom' AND a.outcome='failed'") if json.loads(r['data'] or '{}').get('bloomHit',True)}
        eligible.update(r['pmid'] for r in rows('SELECT pmid,data FROM item_progress') if json.loads(r['data']).get('bloomHit'))
        selected=[]
        for paper in papers:
            p=pmid(paper['pmid'])
            if p not in eligible or not paper.get('doi'):continue
            dest=paper_dir(project,p)/f'{p}.pdf'
            try:validate_pdf(dest);continue
            except Exception:pass
            selected.append(paper)
        papers=selected
        if not papers:raise ValueError('当前纳入集合没有 Bloom 命中且缺失有效 PDF 的已尝试文献')
    cfg=config(); bid=uuid.uuid4().hex
    if a.get('mode')=='zotero':cfg['downloadMode']='zotero'
    if a.get('convertAfter'):
        import markdown_service as markdown
        markdown.ensure_idle(sys.modules[__name__])
        if not markdown.readiness(sys.modules[__name__])['ready']:raise ValueError('请先在设置中准备本地 Markdown 模型')
        cfg.update(convertAfter=True,markdownRequestId=bid)
    with db() as c:
        # Project scope prevents concurrent requests racing to download the same PMID.
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM batches WHERE project=? AND state IN ('queued','running','paused')",(project,)).fetchone():raise ValueError('此项目已有未完成批次，请在任务中心继续或取消后再创建')
        c.execute('INSERT INTO batches(id,project,created,state,snapshot,config,owner) VALUES(?,?,?,?,?,?,?)',(bid,project,time.time(),'queued',str(a.get('snapshot','')),json.dumps(cfg),int(a.get('owner',0))))
        seen=set()
        for paper in papers:
            p=pmid(paper['pmid'])
            if p in seen:continue
            seen.add(p);paper={**paper,'pmid':p}
            c.execute('INSERT INTO items(batch,pmid,paper,state) VALUES(?,?,?,?)',(bid,p,json.dumps(paper,ensure_ascii=False),'queued'))
            if a.get('mode')=='bloom_retry':
                value={'bloomHit':True,'manualRecovery':True,'completedStages':['scihub_bloom'], 'retryStatus':'waiting','nextAttemptAt':time.time()}
                c.execute('INSERT INTO item_progress VALUES(?,?,?)',(bid,p,json.dumps(value)))
    b=one('SELECT * FROM batches WHERE id=?',(bid,));write_json(batch_dir(b)/'manifest.json',{'batch':bid,'project':project,'snapshot':b['snapshot'],'papers':papers,'config':cfg});report(b);launch()
    return {'id':bid,'count':len(seen)}

def finish_markdown(b):
    """Durable one-time handoff, executed by the download worker without a UI."""
    cfg=json.loads(b['config'])
    if not cfg.get('convertAfter'):return None
    import library_service
    flow=library_service.job(sys.modules[__name__])
    if flow and flow['state'] in library_service.ACTIVE:
        result={'state':'stopped','error':'由当前项目流程管理后续阶段'}
        if flow.get('mode')=='clear':write_json(batch_dir(b)/('markdown-followup-'+cfg.get('markdownRequestId',b['id'])+'.json'),result)
        return result
    request=cfg.get('markdownRequestId',b['id'])
    path=batch_dir(b)/('markdown-followup-'+request+'.json')
    previous=json.loads(path.read_text()) if path.exists() else {}
    if previous.get('state') in ('started','empty','failed','stopped'):return previous
    if b['state']!='done':return {'state':'waiting'}
    # A competing worker/list call owns the handoff. Never persist an error on lock contention.
    try:
        with storage.file_lock(batch_dir(b)/'markdown-followup.lock'):
            previous=json.loads(path.read_text()) if path.exists() else {}
            if previous.get('state') in ('started','empty','failed','stopped'):return previous
            try:
                if b.get('owner') and not process_alive(b['owner']):
                    result={'state':'stopped','error':'应用已退出，自动转换未启动；可手动转换已有 PDF'}
                else:
                    import markdown_service as markdown
                    status=markdown.status(sys.modules[__name__])
                    if not status['pdfCount']:
                        result={'state':'empty','error':'本次未获得可转换的 PDF，已保留文献摘要'}
                        try:
                            import vector_service
                            result['vectorFollowup']=vector_service.rpc(sys.modules[__name__],'auto',{'requestId':request,'owner':b.get('owner',0)})
                        except Exception as ex:result['vectorFollowup']={'state':'failed','error':str(ex)}
                    elif status['job'] and status['job']['state'] in ('queued','running','stopping') and status['job'].get('requestId')!=request:
                        return {'state':'waiting','error':'等待当前转换任务完成'}
                    else:
                        result={'state':'started',**markdown.rpc(sys.modules[__name__],'start',{'requestId':request,'owner':b.get('owner',0),'indexAfter':True})}
            except Exception as ex:
                result={'state':'failed','error':'自动转换未启动：'+str(ex)}
            write_json(path,result);return result
    except ValueError:return {'state':'waiting'}

def list_state(project):
    ident(project)
    try:corpus_files.reconcile(sys.modules[__name__])
    except ValueError:pass
    available=recover()
    if available and rows("SELECT 1 FROM batches WHERE state='queued'"):launch()
    batches=rows('SELECT * FROM batches WHERE project=? ORDER BY created DESC',(project,))
    for b in batches:
        b['markdownFollowup']=finish_markdown(b)
        b['config']=json.loads(b['config']);b['items']=rows('SELECT pmid,paper,state,stage,source,error,bytes FROM items WHERE batch=?',(b['id'],))
        states={r['pmid']:json.loads(r['data']) for r in rows('SELECT pmid,data FROM item_progress WHERE batch=?',(b['id'],))}
        attempts=rows('SELECT pmid,stage,outcome FROM attempts WHERE batch=?',(b['id'],))
        for i in b['items']:
            i['title']=json.loads(i.pop('paper')).get('title','');i['progress']=states.get(i['pmid'],{})
        b['bloomSummary']=bloom_summary(b['items'],attempts,states)
        b['counts']=dict(Counter(i['state'] for i in b['items']));b['reportPath']=str(batch_dir(b)/'download_report.txt.gz')
    assets={r['pmid']:json.loads(r['data']) for r in rows('SELECT * FROM assets WHERE project=?',(project,))}
    for asset in assets.values():asset['exists']=asset_path(project,asset).is_file();asset['path']=str(asset_path(project,asset))
    return {'batches':batches,'assets':assets}

def control(a):
    b=one('SELECT * FROM batches WHERE id=? AND project=?',(ident(a['id']),ident(a['project'])));action=a['command']
    if action not in ['pause','resume','cancel','retry']:raise ValueError('无效任务操作')
    if action in ['resume','retry']:
        recover();b=one('SELECT * FROM batches WHERE id=?',(b['id'],))
        if b['state']=='running':raise ValueError('任务仍在运行，请稍后操作')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM batches WHERE project=? AND id<>? AND state IN ('queued','running','paused')",(b['project'],b['id'])).fetchone():raise ValueError('请先完成此项目的其他批次')
            states=('failed','deferred') if action=='retry' else ('paused','cancelled','queued','running')
            marks=','.join('?' for _ in states)
            count=c.execute(f"UPDATE items SET state='queued',error='' WHERE batch=? AND state IN ({marks})",(b['id'],*states)).rowcount
            if not count:raise ValueError('没有可继续或重试的文献')
            # A retry explicitly takes the latest settings (using current download preferences).
            cfg=b['config']
            if action=='retry':
                fresh=config()
                if json.loads(b['config']).get('downloadMode')=='zotero':fresh['downloadMode']='zotero'
                if json.loads(b['config']).get('convertAfter'):fresh.update(convertAfter=True,markdownRequestId=uuid.uuid4().hex)
                cfg=json.dumps(fresh)
            if action=='retry':
                # Explicit user retry starts a new bounded cycle; resume preserves its budget.
                c.execute("DELETE FROM item_progress WHERE batch=? AND pmid IN (SELECT pmid FROM items WHERE batch=? AND state='queued')",(b['id'],b['id']))
                c.execute('DELETE FROM mirror_health WHERE batch=?',(b['id'],))
            c.execute("UPDATE batches SET state='queued',control='',error='',config=?,owner=? WHERE id=?",(cfg,int(a.get('owner',0)),b['id']))
        event(b,'','control',action);launch()
    elif b['state'] in ['queued','running','paused']:
        if b['state']=='running':execute('UPDATE batches SET control=? WHERE id=?',(action,b['id']))
        else:
            target='paused' if action=='pause' else 'cancelled'
            execute('UPDATE batches SET state=?,control=\'\' WHERE id=?',(target,b['id']))
            execute("UPDATE items SET state=? WHERE batch=? AND state IN ('queued','running','paused')",(target,b['id']))
            report(one('SELECT * FROM batches WHERE id=?',(b['id'],)))
    return {'ok':True}

def worker_lock():
    p=storage.project_dir(ROOT,PROJECT)/'metadata/download-worker.lock';p.parent.mkdir(parents=True,exist_ok=True);f=p.open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if f.tell()==0:f.write(b'0');f.flush()
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return f
    except OSError:f.close();return None

def trace_request(record):
    context=HTTP_TRACE.get()
    if context:
        b,p,stage,detail=context
        detail.setdefault('requests',[]).append(record)
        key='fileRequests' if record['role']=='file' else 'entryRequests'
        detail[key]=detail.get(key,0)+1
        timing='downloadSeconds' if record['role']=='file' else 'lookupSeconds'
        times=detail.setdefault('timings',{})
        times[timing]=round(times.get(timing,0)+record['seconds'],3)
        event(b,p,stage,'HTTP 请求明细',**record)

async def request(client,url,*,attempts=3,**kwargs):
    for n in range(attempts):
        started=time.monotonic();record={'role':'entry','url':scihub_retry.safe_url(url),'attempt':n+1}
        try:
            r=await client.get(url,**kwargs)
            record.update(status=r.status_code,finalUrl=scihub_retry.safe_url(str(r.url)),bytes=len(r.content))
            if r.status_code not in [429,500,502,503,504] or n==attempts-1:r.raise_for_status();return r
            delay=max(2**n,scihub_retry.retry_after(r.headers.get('retry-after')))
        except (httpx.TimeoutException,httpx.NetworkError) as exc:
            record.update(kind=scihub_retry.exception_kind(exc))
            if n==attempts-1:raise
            delay=2**n
        except asyncio.CancelledError:
            record['kind']='interrupted';raise
        finally:
            record['seconds']=round(time.monotonic()-started,3);trace_request(record)
        await asyncio.sleep(max(1,delay))
    raise ValueError('请求未完成')

async def fetch_pdf(client,url,path,b,p,stage,attempts=1,md5=None,*,timeout=None,minimum_bytes=0,strict_header=False,attempt_offset=0):
    if urlparse(url).scheme not in ('https','http'):raise ValueError('不支持的 PDF 地址')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    for n in range(attempts):
        started=time.monotonic();total=0
        record={'role':'file','url':url if stage=='europe_pmc_getpdf' else scihub_retry.safe_url(url),'attempt':n+1+attempt_offset}
        try:
            event(b,p,stage,'下载候选文件',url=record['url'],attempt=n+1+attempt_offset)
            async with client.stream('GET',url,**({'timeout':timeout} if timeout is not None else {})) as r:
                record.update(status=r.status_code,finalUrl=scihub_retry.safe_url(str(r.url)),finalHost=r.url.host,
                              redirects=len(r.history),headersSeconds=round(time.monotonic()-started,3))
                if stage=='europe_pmc_getpdf' and r.is_error:
                    # Retain the small getPdf JSON explanation, never a PDF asset.
                    error_body=bytearray()
                    async for chunk in r.aiter_bytes():
                        error_body.extend(chunk[:1024-len(error_body)])
                        if len(error_body)>=1024:break
                    record['error']=error_body.decode('utf-8',errors='replace')
                    record['errorResponseBytes']=len(error_body)
                r.raise_for_status()
                with path.open('wb') as f:
                    async for chunk in r.aiter_bytes():
                        if chunk and not total:record['firstByteSeconds']=round(time.monotonic()-started,3)
                        total+=len(chunk)
                        if total>250*1024*1024:raise ValueError('PDF 超过 250 MB 限制')
                        f.write(chunk)
                        execute('UPDATE items SET bytes=? WHERE batch=? AND pmid=?',(total,b['id'],p)) if total//262144!=(total-len(chunk))//262144 else None
            if total<minimum_bytes:raise ValueError('PDF 文件过小')
            if strict_header:
                with path.open('rb') as f:
                    if not f.read(5)==b'%PDF-':raise ValueError('响应不是 PDF（可能是网页或错误页）')
            result=await asyncio.to_thread(validate_pdf,path,md5)
            record['kind']='success'
            return result
        except asyncio.CancelledError:
            record['kind']='interrupted'
            path.unlink(missing_ok=True);raise
        except Exception as e:
            record['kind']=scihub_retry.exception_kind(e) if isinstance(e,httpx.TransportError) else ('http_error' if isinstance(e,httpx.HTTPStatusError) else 'invalid_pdf')
            path.unlink(missing_ok=True)
            retry=isinstance(e,(httpx.TimeoutException,httpx.NetworkError)) or (isinstance(e,httpx.HTTPStatusError) and e.response.status_code in [429,500,502,503,504])
            event(b,p,stage,'候选下载失败',error=str(e)[:500])
            if not retry or n==attempts-1:raise
            delay=2**n
            if isinstance(e,httpx.HTTPStatusError):
                delay=max(delay,scihub_retry.retry_after(e.response.headers.get('retry-after')))
        finally:
            record.update(bytes=total,seconds=round(time.monotonic()-started,3))
            record['averageBytesPerSecond']=round(total/max(.001,record['seconds']),1)
            trace_request(record)
        await asyncio.sleep(max(1,delay))

async def s3_versions(client,pmcid,attempts):
    token=None;versions=[]
    while True:
        params={'list-type':'2','prefix':pmcid+'.','delimiter':'/'}
        if token:params['continuation-token']=token
        doc=ET.fromstring((await request(client,S3,params=params,attempts=attempts)).content)
        for node in doc.findall('{*}CommonPrefixes/{*}Prefix'):
            if re.fullmatch(re.escape(pmcid)+r'\.\d+/',node.text or ''):versions.append(node.text.rstrip('/'))
        if doc.findtext('{*}IsTruncated')!='true':break
        next_token=doc.findtext('{*}NextContinuationToken')
        if not next_token or next_token==token:raise ValueError('S3 列表分页标记异常')
        token=next_token
    return list(dict.fromkeys(versions))

def s3_pdf(meta,pmcid,p):
    if meta.get('pmcid')!=pmcid:raise ValueError('S3 元数据 PMCID 不一致')
    if meta.get('pmid') and str(meta['pmid'])!=str(p):raise ValueError('S3 元数据 PMID 冲突')
    raw=meta.get('pdf_url')
    if not raw:return None
    u=urlparse(raw)
    if u.scheme!='s3' or u.netloc!='pmc-oa-opendata':raise ValueError('S3 正文地址不属于预期仓库')
    key=unquote(u.path.lstrip('/'));version=str(meta.get('version'))
    if not key.startswith(f'{pmcid}.{version}/') or not key.lower().endswith('.pdf'):raise ValueError('S3 正文对象版本不一致')
    return S3+'/'+quote(key,safe='/'),key,parse_qs(u.query).get('md5',[None])[0]

async def source_s3(client,paper,path,b,cfg):
    p=paper['pmid'];pmcid=pmc_parallel.normalize_pmcid(paper.get('pmcid'))
    if not pmcid:return None,'没有有效 PMCID'
    versions=await s3_versions(client,pmcid,cfg['attempts'])
    if not versions:return None,'S3 未收录此 PMCID'
    current=None
    if len(versions)>1:
        try:
            r=await request(client,'https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/',params={'ids':pmcid,'versions':'yes','format':'json','tool':'ScholarNoteLM'},attempts=1)
            for record in r.json().get('records',[]):
                for v in record.get('versions',[]):
                    if v.get('current') in (True,'true'):current=v.get('pmcid')
        except Exception as e:event(b,p,'pmc_s3','未获得 current 标记，将保留版本选择依据',error=str(e)[:300])
    # Current first; version order is merely a deterministic fallback, never labelled newest.
    versions.sort(key=lambda v:(v!=current,int(v.rsplit('.',1)[1])))
    for version in versions:
        try:
            meta=(await request(client,f'{S3}/{version}/{version}.json',attempts=cfg['attempts'])).json()
            if str(meta.get('version'))!=version.rsplit('.',1)[1]:raise ValueError('JSON 版本与所列版本不一致')
            candidate=s3_pdf(meta,pmcid,p)
            if not candidate:event(b,p,'pmc_s3','版本没有正文 PDF',version=version);continue
            context=HTTP_TRACE.get()
            if context:context[3]['s3PdfFound']=True
            event(b,p,'pmc_s3','找到官方正文 PDF',version=version)
            url,key,md5=candidate
            await fetch_pdf(client,url,path,b,p,'pmc_s3',cfg['attempts'],md5)
            return {'source':'PMC S3','url':url,'key':key,'pmcid':pmcid,'version':meta.get('version'),'isManuscript':meta.get('is_manuscript'),'license':meta.get('license_code'),'isRetracted':meta.get('is_retracted'),'expectedMd5':md5,'selectionReason':'PMC current' if version==current else ('唯一可用版本' if len(versions)==1 else '可用版本；未按版本号推断新旧'),'metadata':meta},''
        except Exception as e:event(b,p,'pmc_s3','版本未下载成功',version=version,error=str(e)[:500])
    return None,'S3 各版本未获得有效正文 PDF（详见日志）'

async def source_europe_pmc_getpdf(client,paper,path,b,cfg,gate):
    return await europe_pmc_pdf.download(sys.modules[__name__],client,paper,path,b,cfg,gate)

async def source_unpaywall(client,paper,path,b,cfg):
    if not paper.get('doi'):return None,'没有 DOI'
    if not cfg['email']:return None,'未配置 Unpaywall 联系邮箱'
    r=await request(client,'https://api.unpaywall.org/v2/'+quote(paper['doi'],safe=''),params={'email':cfg['email']},attempts=1)
    data=r.json();locations=[data.get('best_oa_location'),*data.get('oa_locations',[])];seen=set();slow=False
    for loc in locations:
        if not isinstance(loc,dict):continue
        url=loc.get('url_for_pdf')
        if not url or url in seen:continue
        seen.add(url)
        try:
            stage='unpaywall'
            async with asyncio.timeout(cfg.get('oaFileTimeout',DEFAULTS['oaFileTimeout'])):
                await fetch_pdf(client,url,path,b,paper['pmid'],stage)
            return {'source':'Unpaywall','url':url,'version':loc.get('version'),'license':loc.get('license')},''
        except (TimeoutError,httpx.TimeoutException):
            slow=True
            event(b,paper['pmid'],stage,'候选文件超时，继续其他地址',url=scihub_retry.safe_url(url),kind='file_timeout')
        except Exception:continue
    if slow:raise TimeoutError('OA 文件下载超时')
    return None,'Unpaywall 未获得有效 PDF'

def scihub_publication_guard(b,paper):
    import artifact_state
    import zotero_local
    p=paper['pmid'];e=sys.modules[__name__]
    doi=badr.normalize_doi_for_scihub(paper.get('doi') or '')
    generation=artifact_state.epoch(e,p)
    dest=corpus_files.folder(e,'pdf')/f'{p}.pdf'
    original=zotero_local.fingerprint(dest)
    def current_doi():
        xml=ET.fromstring((corpus_files.base(e)/'pubmed/current.xml').read_bytes())
        if xml.tag!='PubmedArticleSet':return None
        for node,citation,article,data in pubmed_xml.records(xml):
            if citation.findtext('PMID')!=p:continue
            for value in pubmed_xml.doi_elements(node,citation,article,data):
                if (value.get('IdType') or value.get('EIdType') or '').lower()=='doi':return badr.normalize_doi_for_scihub(value.text)
            return ''
        return None
    def guard():
        membership=artifact_state.membership(e)
        row=one('SELECT state,control FROM batches WHERE id=?',(b['id'],))
        if row['state']!='running' or row['control'] or (b.get('owner') and not process_alive(b['owner'])):raise ValueError('批次已停止，未发布浏览器下载')
        if current_doi()!=doi or artifact_state.epoch(e,p)!=generation or p in membership.get('pending',[]):raise ValueError('文献已移出、DOI 或生命周期已改变，未发布浏览器下载')
        if (corpus_files.base(e)/'metadata/pdf-cleared.json').exists():raise ValueError('PDF 已清空，未发布浏览器下载')
        if zotero_local.fingerprint(dest)!=original:raise ValueError('项目 PDF 已出现或改变，不覆盖')
    return guard

async def publish(b,paper,path,info,*,checked=None,guard=None):
    # Prevalidation is internal-only, from killable helpers on the same staging file.
    p=paper['pmid'];validation_start=time.monotonic()
    if checked is None:checked=await asyncio.to_thread(validate_pdf,path,info.get('expectedMd5'))
    elif guard is None:raise ValueError('预校验发布必须提供生命周期与文件指纹检查')
    info['publicationValidationSeconds']=round(time.monotonic()-validation_start,3)
    dest=paper_dir(b['project'],p)/f'{p}.pdf';dest.parent.mkdir(parents=True,exist_ok=True)
    info={**info,**checked,'pmid':p,'pmcid':info.get('pmcid') or paper.get('pmcid'),'path':str(dest.relative_to(storage.project_dir(ROOT,PROJECT))),'downloaded':time.time(),'batch':b['id']}
    with corpus_files.lock(sys.modules[__name__]):
        if guard:
            # Acquire the publication transaction before the last cancellation check.
            # The optional helper has a short DB lock wait and an external hard deadline.
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                guard()
                os.replace(path,dest)
                c.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(b['project'],p,json.dumps(info,ensure_ascii=False)))
                c.execute("UPDATE items SET state='success',source=?,error='',bytes=? WHERE batch=? AND pmid=?",(info['source'],info['bytes'],b['id'],p))
            # Auxiliary receipts must not undo an already committed publication.
            import zotero_local
            try:zotero_local.cache_fingerprint(sys.modules[__name__],dest,checked['sha256'])
            except (OSError,sqlite3.Error):pass
            receipt=path.with_suffix('.metadata.json')
            try:
                receipt.write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
                metadata_path(PROJECT,p).parent.mkdir(parents=True,exist_ok=True)
                os.replace(receipt,metadata_path(PROJECT,p))
            except OSError:pass
            finally:receipt.unlink(missing_ok=True)
        else:
            os.replace(path,dest);write_json(metadata_path(PROJECT,p),info)
            execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(b['project'],p,json.dumps(info,ensure_ascii=False)))
            corpus_files.reconcile_locked(sys.modules[__name__])
    execute("UPDATE items SET state='success',source=?,error='',bytes=? WHERE batch=? AND pmid=?",(info['source'],info['bytes'],b['id'],p))
    remember_sources(paper, info)
    state=progress(b['id'],p)
    if state.get('retryStatus'):
        state['retryStatus']='success' if info['source'] in ('Sci-Hub','Sci-Net') else 'recovered_elsewhere'
        state.pop('nextAttemptAt',None);save_progress(b['id'],p,state)
    event(b,p,'verified','PDF 校验完成',source=info['source'],path=info['path'],sha256=info['sha256'])

def process_alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if not handle:return False
        try:return kernel.WaitForSingleObject(handle,0)==258
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True

async def source_scihub(paper,path,b,cfg,stage,index,bloom,health,detail):
    p=paper['pmid'];bid=b['id'];state=progress(bid,p)
    if not paper.get('doi'):return None,'没有 DOI','skipped'
    if not cfg['mirrors']:return None,'未配置镜像','skipped'
    known_files,known_pages=cached_sources(paper) if stage=='scihub_bloom' or state.get('manualRecovery') else ([],[])
    known_files=[x for x in known_files if x['url'] not in state.get('cachedSourcesTried',[])]
    known_pages=[x for x in known_pages if x not in state.get('cachedSourcesTried',[])]
    if stage=='scihub_bloom':
        state['bloomHit']=bool(bloom and bloom.contains(paper['doi']))
        save_progress(bid,p,state)
        if not state['bloomHit'] and not known_files and not known_pages:return None,'Bloom 未命中或不可用，且无历史来源','skipped'
    retry_stage=stage=='scihub_retry'
    supplemental=retry_stage
    offset=index%len(cfg['mirrors']);order=cfg['mirrors'][offset:]+cfg['mirrors'][:offset]
    tried_key=stage+'Mirrors'
    order=[m for m in order if m not in state.get(tried_key,[])]
    if stage=='scihub_bloom' and not state['bloomHit']:order=[]
    budget_prefix='retry' if retry_stage else 'first'
    budget={'network':state.get(budget_prefix+'NetworkSeconds',0),
            'wait':state.get(budget_prefix+'WaitSeconds',0),
            'networkLimit':scihub_retry.RETRY_BUDGET,'waitLimit':scihub_retry.WAIT_BUDGET,'deferCooldown':True}
    initial_wait=0.
    detail.update(entryRequests=0,fileRequests=0)
    def emit(message,**extra):
        event(b,p,stage,message,**extra)
        if extra.get('kind')=='timings':detail['timings']={k:v for k,v in extra.items() if k.endswith('Seconds')}
        if extra.get('kind')=='request_count':detail.update(entryRequests=extra['entryRequests'],fileRequests=extra['fileRequests'])
        if extra.get('kind')=='deferred':
            detail['deferred']=True;detail['deferReason']=message
        if supplemental and extra.get('kind')=='cooldown':
            state.update(retryStatus='waiting',nextAttemptAt=extra['nextAttemptAt']);save_progress(bid,p,state)
    def consume():
        state['retryUsed']=state.get('retryUsed',0)+1
        state['retryStatus']='running';state.pop('nextAttemptAt',None);save_progress(bid,p,state)
    def on_entry(mirror):
        state[tried_key]=[*state.get(tried_key,[]),mirror]
        save_progress(bid,p,state)
    def on_cached(url):
        state['cachedSourcesTried']=[*state.get('cachedSourcesTried',[]),url]
        save_progress(bid,p,state)
    def on_unverifiable(candidate,evidence,source):
        # Keep uncertain originals in the batch audit area, never in the corpus
        # scanned by Marker/indexing. No user file is replaced or removed.
        folder=batch_dir(b)/'identity_pending'/p;folder.mkdir(parents=True,exist_ok=True)
        name=evidence.get('sha256') or uuid.uuid4().hex
        target=folder/(name+'.pdf')
        os.replace(candidate,target)
        receipt={'pmid':p,'doi':paper['doi'],'title':paper.get('title',''),'identity':evidence,**source,
                 'path':str(target.relative_to(storage.project_dir(ROOT,b['project'])))}
        write_json(target.with_suffix('.json'),receipt)
        detail.setdefault('identityPending',[]).append(receipt)
        state['identityPending']=list(dict.fromkeys([*state.get('identityPending',[]),receipt['path']]))
        save_progress(bid,p,state)
        event(b,p,stage,'PDF 已保留待核验，未进入全文转换或索引',kind='identity_pending',**receipt)
    try:
        if not order and not known_files and not known_pages:
            return None,'本轮镜像请求已消耗（含中断请求），可手动重试','deferred'
        if budget['network']>=budget['networkLimit']:
            return None,'本轮实际请求时间预算已用完，可手动重试','deferred'
        if supplemental:
            state['retryStatus']='waiting';save_progress(bid,p,state)
            delay=max(0.,state.get('nextAttemptAt',0)-time.time())
            if delay>max(0.,budget['waitLimit']-budget['wait']):
                detail['deferred']=True
                return None,'已延期：尚未获得补救请求机会，等待时间超出本轮上限','deferred'
            if delay:
                emit('等待延迟补救',kind='cooldown',nextAttemptAt=state['nextAttemptAt'])
                started=time.monotonic()
                try:await asyncio.sleep(delay)
                finally:
                    initial_wait=time.monotonic()-started;budget['wait']+=initial_wait
        info,timings,requests=await scihub_retry.download(paper['doi'],path,order,health,emit,validate_pdf,
            timeout=cfg['timeout'],supplemental=supplemental,used=state.get('retryUsed',0),consume=consume,budget=budget,on_entry=on_entry,known_files=known_files,known_pages=known_pages,on_cached=on_cached,title=paper.get('title',''),on_unverifiable=on_unverifiable,session_factory=SCI_HUB_BROWSER.get().session if SCI_HUB_BROWSER.get() else None)
        detail.update(timings=timings,requests=requests)
        if info:return info,'','success'
        if any(r.get('kind') in ('browser_error','browser_unavailable') for r in requests):
            return None,'Playwright Chromium 不可用或异常退出；未回退 HTTP，可修复后重试','deferred'
        if detail.get('deferred'):
            reason='已延期：'+('尚未发出本阶段请求' if not detail['entryRequests'] else '部分请求失败，剩余镜像暂不可用')
            return None,reason+'；可稍后重试','deferred'
        if budget['network']>=budget['networkLimit']:
            return None,'实际请求时间达到上限，可稍后重试','deferred'
        if detail.get('identityPending'):
            return None,'PDF 身份待核验；文件保存在本批日志 identity_pending 目录，未发布到文献库','failed'
        if any(r.get('kind')=='identity_mismatch' for r in requests):
            return None,'候选 PDF 内容与目标文献不匹配，未发布；详见身份检查记录','failed'
        return None,'已实际请求镜像，未取得有效 PDF；详见逐次请求日志','failed'
    finally:
        detail.setdefault('timings',{})['cooldownSeconds']=round(detail.get('timings',{}).get('cooldownSeconds',0)+initial_wait,3)
        state[budget_prefix+'NetworkSeconds']=budget['network'];state[budget_prefix+'WaitSeconds']=budget['wait']
        save_progress(bid,p,state)


async def run_queue(entries,workers,attempt):
    """Only fixed workers become tasks; queued papers consume no request budget."""
    queue=asyncio.Queue()
    for entry in entries:queue.put_nowait(entry)
    async def worker():
        while True:
            try:index,item=queue.get_nowait()
            except asyncio.QueueEmpty:return
            try:await attempt(item,index)
            finally:queue.task_done()
    async with asyncio.TaskGroup() as group:
        for _ in range(min(max(1,workers),queue.qsize())):group.create_task(worker())

async def run_batch(b):
    cfg={**DEFAULTS,**json.loads(b['config'])}
    zotero_only=cfg.get('downloadMode')=='zotero'
    if not zotero_only:
        load_sources()
    corpus_files.reconcile(sys.modules[__name__])
    start=time.monotonic();bid=b['id'];bloom=None
    health=scihub_retry.MirrorHealth({r['endpoint']:json.loads(r['data']) for r in rows('SELECT endpoint,data FROM mirror_health WHERE batch=?',(bid,))},
        save=lambda key,value:execute('INSERT OR REPLACE INTO mirror_health VALUES(?,?,?)',(bid,key,json.dumps(value))),lock_dir=ROOT/'data/locks/download-entries')
    if not execute("UPDATE batches SET state='running',error='' WHERE id=? AND state='queued' AND control=''",(bid,)):return
    import scihub_browser
    browser_pool=scihub_browser.BrowserPool(ROOT)
    browser_token=SCI_HUB_BROWSER.set(browser_pool)
    retry_at=max((json.loads(r['data']).get('getPdfNextAttemptAt',0) for r in rows('SELECT data FROM item_progress WHERE batch=?',(bid,))),default=0)
    getpdf_gate=europe_pmc_pdf.RateGate(retry_at)
    try:
        try:
            if not zotero_only:
                bloom_info(ROOT/BUILTIN_BLOOM);bloom=badr.SciHubBloomFilter(str(ROOT/BUILTIN_BLOOM))
        except Exception as e:event(b,'','scihub_bloom','Bloom 不可用，保留后续全量重试',error=str(e))
        for i in rows("SELECT * FROM items WHERE batch=? AND state='queued'",(bid,)):
            paper=json.loads(i['paper']);state=progress(bid,i['pmid'])
            if 'bloomHit' not in state:
                state['bloomHit']=bool(paper.get('doi') and bloom and bloom.contains(paper['doi']))
                save_progress(bid,i['pmid'],state)
            dest=paper_dir(b['project'],i['pmid'])/f"{i['pmid']}.pdf"
            if dest.exists():
                try:
                    check=await asyncio.to_thread(validate_pdf,dest)
                    old=rows('SELECT data FROM assets WHERE project=? AND pmid=?',(b['project'],i['pmid']))
                    previous=json.loads(old[0]['data']) if old else {}
                    previous=previous if previous.get('sha256')==check['sha256'] else {}
                    info={**previous,**check,'source':previous.get('source') or '已有本地 PDF','path':str(dest.relative_to(storage.project_dir(ROOT,PROJECT))),'pmid':i['pmid']}
                    execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(b['project'],i['pmid'],json.dumps(info)))
                    execute("UPDATE items SET state='skipped',source=?,bytes=? WHERE batch=? AND pmid=?",(info['source'],check['bytes'],bid,i['pmid']))
                except Exception as e:event(b,i['pmid'],'existing','已有文件无效，将重新下载',error=str(e))
        timeout=httpx.Timeout(cfg['timeout'],read=max(60,cfg['timeout']))
        async with httpx.AsyncClient(timeout=timeout,follow_redirects=True,max_redirects=10,headers={'User-Agent':'ScholarNoteLM/0.4 (literature research)'}) as client:
            for stage in (['zotero'] if zotero_only else STAGES):
                if stage=='europe_pmc_getpdf':continue  # Executed together with S3.
                if stage=='zotero':
                    import zotero_stage
                    await zotero_stage.run(sys.modules[__name__],b,cfg)
                    continue
                if stage in ['unpaywall','pmc_s3'] and not cfg['fastOa']:continue
                candidates=[i for i in rows("SELECT * FROM items WHERE batch=? AND state IN ('queued','running')",(bid,)) if stage not in progress(bid,i['pmid']).get('completedStages',[])]
                if stage=='scihub_retry':candidates.sort(key=lambda i:not progress(bid,i['pmid']).get('bloomHit',False))
                workers=min(4,max(1,len(cfg['mirrors']))) if stage.startswith('scihub') else cfg['unpaywallConcurrency'] if stage=='unpaywall' else cfg['pmcConcurrency']
                async def attempt(i,index,stage=stage):
                    paper=json.loads(i['paper']);p=i['pmid'];path=batch_dir(b)/'staging'/p/f'{p}.pdf';path.parent.mkdir(parents=True,exist_ok=True);path.unlink(missing_ok=True)
                    execute("UPDATE items SET state='running',stage=?,bytes=0 WHERE batch=? AND pmid=?",(stage,bid,p));started=time.monotonic();info=None;reason='';outcome='failed';detail={}
                    if stage in ('unpaywall','pmc_s3','europe_pmc_getpdf') or stage.startswith('scihub'):detail.update(entryRequests=0,fileRequests=0)
                    trace_token=HTTP_TRACE.set((b,p,stage,detail))
                    try:
                        publication_guard=None
                        if stage.startswith('scihub'):
                            publication_guard=scihub_publication_guard(b,paper)
                            info,reason,outcome=await source_scihub(paper,path,b,cfg,stage,index,bloom,health,detail)
                        elif stage=='unpaywall':
                            async with asyncio.timeout(cfg['oaArticleTimeout']):
                                info,reason=await source_unpaywall(client,paper,path,b,cfg)
                            if reason in ['没有 DOI','未配置 Unpaywall 联系邮箱']:outcome='skipped'
                        elif stage=='europe_pmc_getpdf':
                            info,reason=await source_europe_pmc_getpdf(client,paper,path,b,cfg,getpdf_gate)
                            if reason=='没有有效 PMCID':outcome='skipped'
                        elif stage=='pmc_s3':
                            async with asyncio.timeout(cfg['s3ArticleTimeout']):
                                info,reason=await source_s3(client,paper,path,b,cfg)
                        if info:
                            checked=info.pop('_checked',None);fingerprint=info.pop('_fingerprint',None)
                            if checked is not None:
                                import scihub_identity
                                original_guard=publication_guard
                                def checked_guard():
                                    original_guard()
                                    if scihub_identity.fingerprint(path)!=fingerprint:raise ValueError('暂存 PDF 在校验后改变，未发布')
                                publication_guard=checked_guard
                            await publish(b,paper,path,info,checked=checked,guard=publication_guard);outcome='success'
                    except asyncio.CancelledError:outcome='interrupted';raise
                    except europe_pmc_pdf.Deferred as ex:
                        outcome='deferred';reason=str(ex);detail.update(deferred=True,deferReason=reason)
                        event(b,p,stage,reason,kind='deferred')
                    except (TimeoutError,httpx.TimeoutException):
                        outcome='deferred';reason='请求或下载超时，留待补救 / 手动重试';detail.update(deferred=True,deferReason=reason)
                        event(b,p,stage,reason,kind='timeout')
                    except Exception as e:info=None;outcome='failed';reason=str(e)[:600];event(b,p,stage,'阶段失败',error=reason)
                    finally:
                        HTTP_TRACE.reset(trace_token)
                        path.unlink(missing_ok=True)
                        if not info:execute("UPDATE items SET error=? WHERE batch=? AND pmid=? AND state='running'",(reason,bid,p))
                        state=progress(bid,p)
                        if outcome!='interrupted':
                            state['completedStages']=list(dict.fromkeys([*state.get('completedStages',[]),stage]))
                            pending=set(state.get('deferredStages',[])) & set(STAGES)
                            if outcome=='deferred':pending.add(stage)
                            else:pending.discard(stage)
                            state['deferredStages']=sorted(pending)
                            if stage=='scihub_bloom' and state.get('bloomHit') and not info:
                                state.update(retryStatus='waiting',nextAttemptAt=time.time()+random.uniform(*scihub_retry.FIRST_DELAY))
                                event(b,p,stage,'已加入延迟补救队列',nextAttemptAt=state['nextAttemptAt'])
                            if stage=='scihub_retry' and not info:state['retryStatus']='deferred' if outcome=='deferred' else 'unresolved'
                        save_progress(bid,p,state)
                        execute('INSERT INTO attempts(batch,pmid,stage,outcome,elapsed,detail) VALUES(?,?,?,?,?,?)',(bid,p,stage,outcome,time.monotonic()-started,json.dumps({**detail,**({k:v for k,v in info.items() if k!='metadata'} if info else {'reason':reason})},ensure_ascii=False)))
                if stage=='pmc_s3':
                    await pmc_parallel.run(sys.modules[__name__],b,cfg,attempt)
                    report(one('SELECT * FROM batches WHERE id=?',(bid,)))
                    continue
                if not candidates:continue
                stage_start=time.monotonic();stage_state='completed'
                with db() as c:run_id=c.execute("INSERT INTO stage_runs(batch,stage,started,state) VALUES(?,?,?,'running')",(bid,stage,time.time())).lastrowid
                event(b,'',stage,'阶段开始',candidates=len(candidates),workers=workers)
                try:
                    if stage=='scihub_retry':
                        for hit in (True,False):
                            group=[(n,i) for n,i in enumerate(candidates) if bool(progress(bid,i['pmid']).get('bloomHit'))==hit]
                            await run_queue(group,workers,attempt)
                    else:
                        await run_queue(list(enumerate(candidates)),workers,attempt)
                except BaseException:
                    stage_state='interrupted';raise
                finally:
                    duration=time.monotonic()-stage_start
                    execute('UPDATE stage_runs SET elapsed=?,state=? WHERE id=?',(duration,stage_state,run_id))
                    event(b,'',stage,'阶段结束',wallSeconds=round(duration,3),state=stage_state)
                report(one('SELECT * FROM batches WHERE id=?',(bid,)))
        for i in rows("SELECT * FROM items WHERE batch=? AND state IN ('queued','running')",(bid,)):
            paper=json.loads(i['paper']);dest=abstract_path(b['project'],i['pmid'])
            atomic(dest,f"# {paper.get('title','')}\n\n> 仅 PubMed 摘要，非全文解析结果。\n\nPMID: {i['pmid']}\n\n{paper.get('abstract','')}\n")
            state=progress(bid,i['pmid'])
            if zotero_only:
                reason=state.get('zotero',{}).get('reason') or ('缺少 DOI，无法在 Zotero 中匹配' if not paper.get('doi') else 'Zotero 中未找到可用 PDF')
                execute('UPDATE items SET error=? WHERE batch=? AND pmid=?',(reason,bid,i['pmid']))
            pending=set(state.get('deferredStages',[])) & set(STAGES)
            # A completed second Sci-Hub pass supersedes a deferred first pass.
            if state.get('retryStatus')=='unresolved':pending.discard('scihub_bloom')
            final_state='deferred' if pending or state.get('retryStatus')=='deferred' else 'failed'
            if final_state=='deferred':execute('UPDATE items SET error=? WHERE batch=? AND pmid=?',('部分来源超时或暂不可用，可手动重试；详见下载报告',bid,i['pmid']))
            if state.get('identityPending'):
                execute('UPDATE items SET error=? WHERE batch=? AND pmid=?',('已有 PDF 身份待核验，保存在批次日志 identity_pending 目录；未发布到文献库'+('；另有来源延期' if final_state=='deferred' else ''),bid,i['pmid']))
            execute('UPDATE items SET state=? WHERE batch=? AND pmid=?',(final_state,bid,i['pmid']))
        execute("UPDATE batches SET state='done',control='' WHERE id=?",(bid,))
    except asyncio.CancelledError:
        control_value=one('SELECT * FROM batches WHERE id=?',(bid,))['control'];state='cancelled' if control_value=='cancel' else 'paused'
        execute("UPDATE items SET state=? WHERE batch=? AND state IN ('queued','running')",(state,bid));execute("UPDATE batches SET state=?,control='' WHERE id=?",(state,bid));event(b,'','control',state)
    except Exception as e:
        execute("UPDATE batches SET state='paused',control='',error=? WHERE id=?",(str(e)[:600],bid));execute("UPDATE items SET state='paused' WHERE batch=? AND state IN ('queued','running')",(bid,));event(b,'','error','批次中断',error=str(e))
    finally:
        await browser_pool.close()
        SCI_HUB_BROWSER.reset(browser_token)
        if bloom:bloom.close()
        execute('UPDATE batches SET elapsed=elapsed+? WHERE id=?',(time.monotonic()-start,bid))
        finished=one('SELECT * FROM batches WHERE id=?',(bid,));report(finished)
        if finished['state']=='done':corpus_files.update_missing_pdf_report(sys.modules[__name__])

async def monitored(b):
    task=asyncio.create_task(run_batch(b))
    try:
        while not task.done():
            await asyncio.sleep(.35)
            state=one('SELECT * FROM batches WHERE id=?',(b['id'],))
            owner=b.get('owner',0);alive=True
            if owner:alive=process_alive(owner)
            if state['control'] or not alive:
                task.cancel();await task;break
        await task
    finally:
        if not task.done():task.cancel();await task

def worker():
    lock=worker_lock()
    if lock is None:return
    try:
        # Old running state while holding the exclusive lock means the last worker died.
        execute("UPDATE items SET state='paused' WHERE batch IN (SELECT id FROM batches WHERE state='running') AND state IN ('queued','running')")
        execute("UPDATE batches SET state='paused',error='下载进程中断，可继续' WHERE state='running'")
        idle=0
        while idle<4:
            batches=rows("SELECT * FROM batches WHERE state='queued' ORDER BY created LIMIT 1")
            if not batches:time.sleep(.5);idle+=1;continue
            idle=0;asyncio.run(monitored(batches[0]));finish_markdown(one('SELECT * FROM batches WHERE id=?',(batches[0]['id'],)))
    finally:lock.close()

def open_local(path):
    path=Path(path).resolve()
    if not (path.is_relative_to(ROOT/'data/reference') or path.is_relative_to(storage.project_dir(ROOT,PROJECT))) or not path.exists():raise ValueError('文件不存在或不属于当前项目')
    if sys.platform=='darwin':subprocess.Popen(['open',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    elif os.name=='nt':os.startfile(str(path))
    else:subprocess.Popen(['xdg-open',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'path':str(path)}

def download_rpc(action,a):
    if action=='settings':return get_settings()
    if action=='settings.save':return save_settings(a)
    if action=='start':return create(a)
    if action=='list':return list_state(a['project'])
    if action=='control':return control(a)
    if action=='report':
        b=one('SELECT * FROM batches WHERE id=? AND project=?',(ident(a['id']),ident(a['project'])));path=batch_dir(b)/'download_report.txt'
        report(b)
        text=compact_io.read_text(path)
        if a.get('open'):
            if a.get('folder'):return open_local(path.parent)
            exported=path.parent/'exports/download_report.txt';atomic(exported,text)
            return open_local(exported)
        return {'text':text,'path':str(compact_io.compressed_path(path))}
    if action=='open':
        asset=json.loads(one('SELECT data FROM assets WHERE project=? AND pmid=?',(ident(a['project']),pmid(a['pmid'])))['data']);path=asset_path(a['project'],asset);return open_local(path.parent if a.get('folder') else path)
    if action=='import':
        project=ident(a['project']);p=pmid(a['paper']['pmid']);dest=paper_dir(project,p)/f'{p}.pdf';dest.parent.mkdir(parents=True,exist_ok=True);tmp=dest.with_suffix('.import')
        if rows("SELECT 1 FROM batches WHERE project=? AND state IN ('queued','running','paused')",(project,)):raise ValueError('请先结束或取消当前批次，再关联本地 PDF')
        content=base64.b64decode(a['base64'],validate=True)
        if len(content)>25_000_000:raise ValueError('导入文件不能超过 25 MB')
        try:
            atomic(tmp,content);checked=validate_pdf(tmp);info={**checked,'pmid':p,'path':str(dest.relative_to(storage.project_dir(ROOT,PROJECT))),'source':'用户关联','downloaded':time.time(),'identity':'用户关联，未自动验证正文身份'};os.replace(tmp,dest);write_json(metadata_path(PROJECT,p),info);execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(project,p,json.dumps(info)));return info
        finally:tmp.unlink(missing_ok=True)
    if action=='clear':return clear_downloads(a)
    if action=='export':return package_current(a)
    raise ValueError('未知下载操作')

def idle_project(project):
    if rows("SELECT 1 FROM batches WHERE project=? AND state IN ('queued','running','paused')",(project,)):
        raise ValueError('请先完成或取消当前项目的下载批次')

def clear_downloads(a):
    project=ident(a['project']);idle_project(project)
    import markdown_service
    markdown_service.ensure_idle(sys.modules[__name__])
    if a.get('confirm')!=project:raise ValueError('请确认清空当前项目的 PDF 和摘要')
    lock=worker_lock()
    if lock is None:raise ValueError('下载进程尚未退出，请稍后再试')
    try:
        with corpus_files.lock(sys.modules[__name__]):
            base=storage.project_dir(ROOT,project);targets=[];counts={'pdf':0,'abstracts':0,'packages':0}
            for folder,pattern in [('pdf','*.pdf'),('abstracts','*.md'),('packages','*.zip')]:
                parent=base/folder
                if parent.is_symlink():raise ValueError('不能清理符号链接目录')
                for path in parent.rglob(pattern):
                    if path.is_symlink():raise ValueError('不能清理符号链接文件')
                    if path.is_file():targets.append(path);counts[folder]+=1
            # Invalidate asset records first; file existence is always checked before showing success.
            for path in targets:path.unlink()
            execute('DELETE FROM assets WHERE project=?',(project,))
            for f in (base/'metadata/downloads').glob('*.json'):f.unlink()
            record={'action':'clear-downloads','time':time.time(),'project':project,**counts}
            write_json(base/'logs'/f'clear-{time.time_ns()}.json',record)
            return counts
    finally:lock.close()

def package_current(a):
    project=ident(a['project']);idle_project(project);base=storage.project_dir(ROOT,project)
    xml=base/'pubmed/current.xml'
    if not xml.is_file():raise ValueError('请先生成当前合并 XML')
    raw=xml.read_bytes();doc=ET.fromstring(raw)
    allowed={pmid(c.findtext('PMID')) for _,c,_,_ in pubmed_xml.records(doc) if c.findtext('PMID')}
    if not allowed:raise ValueError('当前 XML 没有可打包的文献')
    folder=base/'packages'
    if folder.is_symlink():raise ValueError('打包目录不能是符号链接')
    folder.mkdir(parents=True,exist_ok=True);dest=folder/'current-literature.zip';tmp=folder/(uuid.uuid4().hex+'.tmp')
    counts={'pdf':0,'abstracts':0};missing=[];entries=[]
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('pubmed/current.xml',raw)
            for p in sorted(allowed,key=int):
                found=[]
                for sub,ext in [('pdf','pdf'),('abstracts','md')]:
                    path=base/sub/f'{p}.{ext}'
                    if path.is_symlink() or path.parent.is_symlink():raise ValueError('打包来源不能是符号链接')
                    if path.is_file():
                        if sub=='pdf':validate_pdf(path)
                        z.write(path,f'{sub}/{path.name}');counts[sub]+=1;found.append(sub)
                entries.append({'pmid':p,'files':found})
                if not found:missing.append(p)
            if not sum(counts.values()):raise ValueError('当前 XML 对应的 PDF 和摘要文件均为空')
            manifest={'project':project,'snapshot':a.get('snapshot',''),'created':time.time(),'xmlSha256':hashlib.sha256(raw).hexdigest(),'counts':counts,'missing':missing,'articles':entries}
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        with zipfile.ZipFile(tmp) as z:
            if z.testzip():raise ValueError('压缩包完整性校验失败')
        os.replace(tmp,dest)
        return {'path':str(dest),'count':counts['pdf'],**counts,'missing':len(missing)}
    finally:tmp.unlink(missing_ok=True)

def dispatch_rpc(action,a):
    global PROJECT
    if a.get('project'):PROJECT=ident(a['project'])
    if action.startswith('zotero.'):
        import zotero_import
        return zotero_import.rpc(sys.modules[__name__],action.removeprefix('zotero.'),a)
    if action=='llm.test':
        from review_llm import test_connection
        return asyncio.run(test_connection(a.get('profile',{})))
    if action.startswith('reader.'):
        import reader_service
        return reader_service.rpc(sys.modules[__name__],action.removeprefix('reader.'),a)
    if action.startswith('qa.'):
        import qa_service
        return qa_service.rpc(sys.modules[__name__],action.removeprefix('qa.'),a)
    if action.startswith('review.'):
        import review_service
        return review_service.rpc(sys.modules[__name__],action.removeprefix('review.'),a)
    if action.startswith('storage.'):
        op=action.removeprefix('storage.')
        if op=='initialize':storage.initialize(ROOT);return storage.status(ROOT)
        if op=='status':return storage.status(ROOT,a.get('project',''))
        if op=='register':
            with storage.file_lock(ROOT/'config/catalog.lock'):return storage.register(ROOT,a)
        if op=='delete':
            import library_service
            with storage.file_lock(ROOT/'config/catalog.lock'):
                storage.project_dir(ROOT,PROJECT)
                job=library_service.job(sys.modules[__name__])
                if (job and job.get('state') in library_service.ACTIVE) or library_service.running(sys.modules[__name__]):
                    raise ValueError('请先完成或停止当前项目的下载、转换、索引和综述任务，再删除项目')
                return storage.delete_project(ROOT,a)
        if op=='move':return storage.move_workspace(ROOT,a['path'])
        if op=='choose':return storage.choose_folder()
        if op=='state.read':return storage.read_state(ROOT)
        if op=='state.write':
            with storage.file_lock(ROOT/'config/catalog.lock'):return storage.write_state(ROOT,a['state'])
        if op=='open':return open_local(storage.project_dir(ROOT,PROJECT))
        raise ValueError('未知存储操作')
    if action.startswith('vector.'):
        import vector_service
        return vector_service.rpc(sys.modules[__name__],action.removeprefix('vector.'),a)
    if action.startswith('markdown.'):
        import markdown_service
        return markdown_service.rpc(sys.modules[__name__],action.removeprefix('markdown.'),a)
    return download_rpc(action,a)

def rpc(action,a):
    global PROJECT
    if a.get('project'):PROJECT=ident(a['project'])
    import library_service
    if action.startswith('library.'):return library_service.rpc(sys.modules[__name__],action.removeprefix('library.'),a)
    mutating=action in ('start','import','clear','markdown.start','markdown.reconcile','vector.start','qa.start','reader.start') or (action=='control' and a.get('command') in ('resume','retry')) or action in ('review.start','review.writing.start','review.writing.prepare','review.writing.prepare.resume','review.writing.reset','review.writing.retry')
    if action=='control' and a.get('command')=='resume':
        current=library_service.job(sys.modules[__name__])
        if current and current['state'] in library_service.ACTIVE and current.get('downloadId')==a.get('id'):a={**a,'workflowId':current['id']}
    if mutating:
        with storage.file_lock(corpus_files.base(sys.modules[__name__])/'metadata/library-operations.lock'):
            library_service.check_owner(sys.modules[__name__],a)
            return dispatch_rpc(action,a)
    return dispatch_rpc(action,a)

if __name__=='__main__':
    if '--worker' in sys.argv:
        PROJECT=ident(sys.argv[sys.argv.index('--project')+1])
        with storage.file_lock(ROOT/'config/storage.lock',shared=True):worker()
    else:
        try:
            req=json.load(sys.stdin);result=rpc(req['action'],req.get('args',{}));print(json.dumps({'ok':True,'data':result},ensure_ascii=False))
        except Exception as e:print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));sys.exit(1)
