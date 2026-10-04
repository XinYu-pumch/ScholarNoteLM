"""Durable project preparation and explicitly scoped maintenance.

One coordinator owns a pipeline; each stage still uses its existing worker.
Opening/closing a view never drives the next stage.
"""
import json,os,shutil,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
import corpus_files as files,storage

ACTIVE=('queued','running','stopping')
def read(path,default=None):return json.loads(path.read_text()) if path.is_file() else default
def path(e):return files.base(e)/'metadata/library-job.json'
def job(e):
    j=read(path(e))
    if j and not j.get('pid'):
        j['pid']=read(files.base(e)/('logs/library-'+j['id'])/'process.json',{}).get('pid',0)
    if j and j['state'] in ACTIVE and ((j.get('pid') and not e.process_alive(j['pid'])) or (not j.get('pid') and time.time()-j.get('created',time.time())>30)):
        j.update(state='interrupted',error='流程进程已退出。已完成内容保留，可再次更新。');e.write_json(path(e),j)
    return j

def check_owner(e,a):
    import zotero_import
    z=zotero_import.current_job(e)
    if z and z.get("state") in ACTIVE:raise ValueError("Zotero 导入正在运行，请先完成或取消导入")
    j=job(e)
    if j and j['state'] in ACTIVE and a.get('workflowId')!=j['id']:
        raise ValueError('一键更新或清理正在运行，请先停止当前流程')

def xml_hash(e):
    import hashlib
    p=files.base(e)/'pubmed/current.xml'
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ''

def worker_alive(e,pid):
    if not pid:return False
    if os.name!='nt':
        try:
            reaped,_=os.waitpid(pid,os.WNOHANG)
            if reaped:return False
        except ChildProcessError:pass
    return e.process_alive(pid)

def running(e):
    import markdown_service as m,vector_service as v,review_service as r,review_writing as w
    result=[]
    import zotero_import
    z=zotero_import.current_job(e)
    if z and z.get("state") in ACTIVE:result.append(("zotero",z))
    import qa_service
    for qa in qa_service.jobs(e,include_finished=True):
        if qa.get('state') in ACTIVE or (qa.get('pid') and time.time()-qa.get('finished',0)<60 and worker_alive(e,qa['pid'])):result.append(('qa',qa))
    e.recover()
    for b in e.rows("SELECT * FROM batches WHERE project=? AND state IN ('queued','running','paused')",(e.PROJECT,)):
        result.append(('download',b))
    for kind,j in [('markdown',m.read_job(e)),('vector',v.read_job(e))]:
        if j and (j['state'] in ACTIVE or (j.get('pid') and time.time()-j.get('finished',0)<60 and worker_alive(e,j['pid']))):result.append((kind,j))
    root=files.base(e)/'review'
    for directory in root.iterdir() if root.exists() else []:
        if not directory.is_dir() or directory.is_symlink() or not (directory/'review.json').is_file():continue
        for kind,record in [('outline',r.vstate(e,directory.name,'current')),('writing',w.job(e,directory.name))]:
            if record and (record.get('state') in ACTIVE or (record.get('pid') and time.time()-record.get('finished',0)<60 and worker_alive(e,record['pid']))):
                result.append((kind,{**record,'name':directory.name}))
    return result

def stop_children(e):
    import markdown_service as m,vector_service as v,review_service as r
    for kind,record in running(e):
        if kind=='zotero':e.atomic(files.base(e)/'metadata/zotero-imports'/record['id']/'cancel','cancel')
        elif kind=='download':e.control({'id':record['id'],'project':e.PROJECT,'command':'cancel'})
        elif kind=='markdown':m.rpc(e,'stop',{})
        elif kind=='vector':v.rpc(e,'stop',{})
        elif kind=='outline':r.rpc(e,'cancel',{'name':record['name']})
        elif kind=='writing':r.rpc(e,'writing.cancel',{'name':record['name']})
        elif kind=='qa':
            import qa_service
            qa_service.rpc(e,'cancel',{'runId':record['id']})

def inventory(e,scope='index',redundant=False):
    base=files.base(e);counts={}
    for name,pattern in [('pdf','*.pdf'),('markdown','*.md'),('markdown/raw','*.md'),('pdf/redundant','*.pdf')]:
        counts[name]=sum(1 for p in (base/name).rglob(pattern) if p.is_file()) if name=='pdf/redundant' else sum(1 for p in (base/name).glob(pattern) if p.is_file())
    counts['chunks']=0
    db=base/'vectors/chunks.sqlite3'
    if db.is_file():
        with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='chunks'").fetchone():counts['chunks']=c.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
    return {'project':e.PROJECT,'scope':scope,'includeRedundant':redundant,'counts':counts}

def start(e,a,mode='update'):
    with storage.file_lock(files.base(e)/'metadata/library-operations.lock'):
        check_owner(e,{})
        if mode=='update' and running(e):raise ValueError('请先完成或停止当前项目的下载、转换、索引或综述任务')
        if mode=='clear':
            if a.get('confirm')!=e.PROJECT:raise ValueError('请确认当前项目')
            if a.get('scope') not in ('pdf','markdown','index'):raise ValueError('清理范围无效')
        elif not files.current(e):raise ValueError('请先添加 PubMed 文献')
        j={'id':uuid.uuid4().hex,'mode':mode,'state':'queued','stage':'waiting','created':time.time(),'pid':0,'scope':a.get('scope'),'includeRedundant':bool(a.get('includeRedundant')),'stages':[],'xmlHash':xml_hash(e)}
        e.write_json(path(e),j)
        log=files.folder(e,'logs/library-'+j['id'])
        env={**os.environ,'SCHOLARNOTELM_ROOT':str(e.ROOT),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
        try:
            with (log/'worker.log').open('ab') as out:
                p=subprocess.Popen([sys.executable,str(e.ROOT/'services/downloader/library_worker.py'),'--project',e.PROJECT,'--job',j['id']],env=env,cwd=e.ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=out,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}))
            # Child owns job updates. Keep its PID in a separate receipt.
            e.write_json(log/'process.json',{'pid':p.pid})
        except Exception:
            j.update(state='failed',error='无法启动项目流程');e.write_json(path(e),j);raise
        return {'id':j['id']}

class Stopped(Exception):pass

def run(e,ident):
    import markdown_service as m,vector_service as v,vector_chunks as c
    j=read(path(e))
    if not j or j['id']!=ident:return
    j.update(pid=os.getpid(),state='running');log=files.folder(e,'logs/library-'+ident)
    def save():e.write_json(path(e),j);e.write_json(log/'result.json',j)
    def check():
        if (files.base(e)/'metadata'/('library-stop-'+ident)).exists():raise Stopped()
        if j['mode']=='update' and xml_hash(e)!=j['xmlHash']:raise ValueError('当前 XML 已改变，流程已停止。请重新点击一键更新')
    def stage(name):check();j['stage']=name;save()
    def wait_for(get):
        while True:
            check();record=get()
            if not record:raise ValueError('阶段任务记录丢失')
            if record['state'] not in (*ACTIVE,'paused') and not worker_alive(e,record.get('pid')):return record
            time.sleep(.4)
    def record(name,result):
        j['stages'].append({'stage':name,'state':result.get('state'),'failed':result.get('failed',0),'completed':result.get('completed',0),'skipped':result.get('skipped',0),'error':result.get('error','')});save()
        if result.get('state') in ('stopped','cancelled','interrupted'):raise Stopped()
    try:
        save()
        with storage.file_lock(e.ROOT/'config/storage.lock',shared=True):
            if j['mode']=='clear':
                stage('stopping');stop_children(e)
                deadline=time.monotonic()+300
                while running(e):
                    check()
                    if time.monotonic()>deadline:raise ValueError('后台任务尚未退出，未删除文件。待任务停止后重试')
                    time.sleep(.5)
                stage('clearing');j['result']=clear_idle(e,j);save()
            else:
                stage('reconcile')
                with files.lock(e):
                    (files.base(e)/'metadata/pdf-cleared.json').unlink(missing_ok=True)
                    result=files.reconcile_locked(e);result.update(files.register_local_pdfs(e))
                    result.update(files.update_missing_pdf_report_locked(e))
                if result.get('errors') or result.get('invalid'):j['warnings']=result.get('errors',[])+result.get('invalid',[])
                stage('download');status=m.status(e);wanted={i['pmid'] for i in status['items'] if not i['pdf'] and not i['abstractFallback']}
                articles,_=c.xml_articles(e)
                if wanted:
                    result=e.rpc('start',{'project':e.PROJECT,'workflowId':ident,'papers':[articles[p] for p in sorted(wanted)],'owner':0})
                    j['downloadId']=result['id'];save()
                    result=wait_for(lambda:e.one('SELECT * FROM batches WHERE id=?',(result['id'],)))
                    result['failed']=len(e.rows("SELECT 1 FROM items WHERE batch=? AND state IN ('failed','deferred')",(result['id'],)))
                    record('download',result)
                stage('markdown');status=m.status(e);pending=[i['pmid'] for i in status['items'] if i['pdf'] and (not i['ready'] or i['needsCleaning'] or i.get('needsConversion'))]
                if pending:
                    e.rpc('markdown.start',{'project':e.PROJECT,'workflowId':ident,'pmids':pending,'indexAfter':False})
                    record('markdown',wait_for(lambda:m.read_job(e)))
                stage('index')
                # Explicit pipeline indexing is independent of the legacy autoIndex preference.
                python=m.runtime(e.ROOT)
                req={'action':'vector.start','args':{'project':e.PROJECT,'workflowId':ident}}
                proc=subprocess.run([str(python),str(e.ROOT/'services/downloader/engine.py')],input=json.dumps(req),text=True,capture_output=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(e.ROOT)},timeout=120)
                value=json.loads(proc.stdout)
                if not value.get('ok'):raise ValueError(value.get('error','索引启动失败'))
                record('index',wait_for(lambda:v.read_job(e)))
                status=m.status(e);docs=c.documents(e,v.profile(v.config(e)))
                indexed={d['pmid'] for d in docs if d['indexed']}
                j['unindexed']=[i['pmid'] for i in status['items'] if i['pmid'] not in indexed]
            j['state']='partial' if j.get('unindexed') or any(s.get('failed') or s['state']=='failed' for s in j['stages']) else 'done'
    except Stopped:
        stop_children(e);j['state']='stopping';save()
        while running(e):time.sleep(.5)
        j['state']='stopped'
    except Exception as ex:
        j.update(state='stopping',error=str(ex));save()
        stop_children(e)
        deadline=time.monotonic()+300
        while running(e) and time.monotonic()<deadline:time.sleep(.5)
        j['state']='failed'
    finally:j['finished']=time.time();save()

def safe_remove(base,target):
    for p in (target,*target.parents):
        if p==base:break
        if p.is_symlink():raise ValueError('不能清理符号链接目录')
    if target.is_dir():
        if any(p.is_symlink() for p in target.rglob('*')):raise ValueError('不能清理含符号链接的目录')
        shutil.rmtree(target)
    elif target.exists():target.unlink()

def clear_idle(e,j):
    import vector_service as v,artifact_state
    base=files.base(e);scope=j['scope'];counts=inventory(e,scope,j['includeRedundant'])
    with storage.file_lock(base/'metadata/library-operations.lock'),v.index_lock(e),files.lock(e):
        if running(e):raise ValueError('后台任务尚未退出，未清理')
        targets=[base/'vectors']
        if scope in ('pdf','markdown'):targets += [base/'markdown',base/'metadata/markdown']
        if scope=='pdf':
            targets += [base/'abstracts',base/'packages']
            targets += [base/'pdf'] if j['includeRedundant'] else list((base/'pdf').glob('*.pdf'))
        # Validate all paths before deleting any of them.
        for target in targets:
            for p in (target,*target.parents):
                if p==base:break
                if p.is_symlink():raise ValueError('清理目标包含符号链接，未删除')
            if target.is_dir() and any(p.is_symlink() for p in target.rglob('*')):raise ValueError('清理目标包含符号链接，未删除')
        e.write_json(base/'metadata/index-cleared.json',{'time':time.time()})
        e.write_json(base/'metadata/index-generation.json',{'id':uuid.uuid4().hex})
        if scope in ('pdf','markdown'):
            state=artifact_state.membership(e)
            for p in files.current(e) or []:state.setdefault('epochs',{})[p]=state.get('epochs',{}).get(p,0)+1
            e.write_json(base/'metadata/corpus-membership.json',state)
        for target in targets:safe_remove(base,target)
        if scope=='pdf':
            e.write_json(base/'metadata/pdf-cleared.json',{'time':time.time()})
            for record in e.rows('SELECT pmid,data FROM assets WHERE project=?',(e.PROJECT,)):
                if j['includeRedundant'] or not json.loads(record['data']).get('archived'):
                    e.execute('DELETE FROM assets WHERE project=? AND pmid=?',(e.PROJECT,record['pmid']))
        for filename in ('vector-job.json','vector-process.json'):
            (base/'metadata'/filename).unlink(missing_ok=True)
        if scope in ('pdf','markdown'):
            for filename in ('markdown-job.json','markdown-process.json'):(base/'metadata'/filename).unlink(missing_ok=True)
        return counts

def rpc(e,op,a):
    if op=='status':return {'job':job(e)}
    if op=='plan':return inventory(e,a.get('scope','index'),bool(a.get('includeRedundant')))
    if op=='start':return start(e,a)
    if op=='clear':return start(e,a,'clear')
    if op=='stop':
        j=job(e)
        if j and j['state'] in ACTIVE:e.atomic(files.base(e)/'metadata'/('library-stop-'+j['id']),'stop')
        return {'ok':True}
    if op=='overview':
        import markdown_service as m,vector_chunks as c,vector_service as v
        import status_cache
        status=m.status(e);docs=status_cache.documents(e,v.profile(v.config(e)))
        root=files.base(e)/'review'
        reviews=sum(1 for d in root.iterdir() if d.is_dir() and not d.is_symlink() and (d/'review.json').is_file()) if root.exists() else 0
        return {'papers':len(files.current(e) or []),'pdf':status['pdfCount'],'indexed':sum(d['indexed'] for d in docs),'reviews':reviews}
    raise ValueError('未知文献流程操作')
