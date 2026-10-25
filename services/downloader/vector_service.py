"""Local evidence store, explicit embedding API, resumable per-document indexing."""
import managed_sqlite
import concurrent.futures,json,math,os,re,sqlite3,struct,subprocess,sys,time,uuid
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlparse
import corpus_files as files,storage,vector_chunks as chunks
import embedding_providers as providers

DEFAULTS={'baseUrl':'','model':'Pro/BAAI/bge-m3','modelRevision':'','apiKey':'','batchSize':64,'concurrency':2,'timeout':60,'autoIndex':True,'adaptive':False,'rpm':60,'tpm':120000}
ACTIVE=('queued','running','stopping')
TEST_TEXT='ScholarNoteLM embedding connection test.'
def endpoint(cfg):return cfg['baseUrl'].rstrip('/') if cfg['baseUrl'].rstrip('/').endswith('/embeddings') else cfg['baseUrl'].rstrip('/')+'/embeddings'
def config(e):
    import project_embedding
    return project_embedding.config(e)
def public(cfg):return {**{k:v for k,v in cfg.items() if k!='apiKey' and not k.startswith('_')},'hasKey':bool(cfg.get('apiKey'))}
def legacy_profile(cfg):
    identity=[cfg['baseUrl'],cfg['model'],cfg.get('modelRevision',''),chunks.TEMPLATE]
    if providers.protocol(cfg):identity.append(providers.protocol(cfg))
    return chunks.digest(identity)
def profile(cfg):
    # Canonical identity is the actual HTTP endpoint, preserving full-URL presets.
    return legacy_profile({**cfg,'baseUrl':endpoint(cfg)})

def profile_aliases(cfg):
    url=endpoint(cfg)
    return list(dict.fromkeys([profile(cfg),legacy_profile({**cfg,'baseUrl':url[:-len('/embeddings')]})]))

def cache_profile(e,cfg):
    """Resolve old URL spelling without writing, rebuilding, or changing vectors.

    Prefer the canonical store if present. Otherwise continue using the existing
    historical store for both spellings, including subsequent indexing writes.
    """
    aliases=profile_aliases(cfg);db=files.base(e)/'vectors/chunks.sqlite3'
    if db.is_file():
        with managed_sqlite.connect(db.as_uri()+'?mode=ro',uri=True) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='profiles'").fetchone():
                for pid in aliases:
                    if c.execute('SELECT 1 FROM profiles WHERE id=?',(pid,)).fetchone():return pid
    return aliases[0]

def settings(e):
    cfg=config(e)
    import retrieval_settings,embedding_profiles,project_embedding
    data=embedding_profiles.store(e)
    return {'profiles':[{**public({**DEFAULTS,**p}),'verified':retrieval_settings.verified(e.ROOT,{**DEFAULTS,**p})} for p in data['profiles']],
            'projectModel':public(cfg),'connection':project_embedding.connection(cfg),'storedIndex':stored_index(e,cfg),
            'presets':embedding_profiles.builtins(),'activeProfile':data['activeProfile'],'apiVerified':retrieval_settings.verified(e.ROOT,cfg),'config':public(cfg),'configured':bool(cfg['baseUrl'] and cfg['model']),'runtimeReady':(e.ROOT/('runtimes/marker/Scripts/python.exe' if os.name=='nt' else 'runtimes/marker/bin/python')).is_file(),'splitter':{'version':chunks.SPLITTER,'maxChars':8192,'minChars':1,'method':'period-balanced'}}

def stored_index(e,cfg):
    """Local inventory, distinct from current-model/material readiness."""
    result={'documents':0,'vectors':0,'models':[]}
    if not getattr(e,'PROJECT',None):return result
    path=files.base(e)/'vectors/chunks.sqlite3'
    if not path.is_file():return result
    with managed_sqlite.connect(path.as_uri()+'?mode=ro',uri=True) as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'profiles','indexed','embeddings'}<=tables:return result
        result['documents']=c.execute('SELECT COUNT(DISTINCT pmid) FROM indexed').fetchone()[0]
        result['vectors']=c.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0]
        for pid,raw in c.execute('SELECT id,config FROM profiles'):
            saved=json.loads(raw);count=c.execute('SELECT COUNT(*) FROM indexed WHERE profile=?',(pid,)).fetchone()[0]
            if count:result['models'].append({'model':saved.get('model',''),'baseUrl':saved.get('baseUrl',''),
                    'documents':count,'current':pid in profile_aliases(cfg)})
    return result
def validated(e,a):
    import embedding_profiles
    cfg=embedding_profiles.form(e,a)
    for k in DEFAULTS:
        if k in a and k!='apiKey':cfg[k]=a[k]
    if a.get('clearKey'):cfg['apiKey']=''
    elif a.get('apiKey'):cfg['apiKey']=a['apiKey'].strip()
    for k in ('baseUrl','model','modelRevision','apiKey'):
        if not isinstance(cfg[k],str) or len(cfg[k])>2000:raise ValueError('Embedding 配置格式无效')
        cfg[k]=cfg[k].strip()
    if cfg['baseUrl']:
        url=urlparse(cfg['baseUrl'])
        if url.scheme not in ('https','http') or not url.hostname or url.username or url.password or url.query or url.fragment:raise ValueError('请填写不含凭据、查询参数的 HTTP(S) API 地址')
        if url.scheme=='http' and url.hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('远程服务请使用 HTTPS；HTTP 仅用于本机服务')
        cfg['baseUrl']=cfg['baseUrl'].rstrip('/')
    for k,lo,hi in [('batchSize',1,128),('concurrency',1,4),('timeout',10,300),('rpm',1,1000000000),('tpm',1,1000000000)]:
        if type(cfg[k]) is not int or not lo<=cfg[k]<=hi:raise ValueError(f'{k} 必须在 {lo}–{hi} 之间')
    if type(cfg.get('adaptive',False)) is not bool:raise ValueError('自动调度选项无效')
    if cfg.get('adaptive') and cfg['tpm']<8192:raise ValueError('自动调度要求 TPM 至少为 8192')
    if type(cfg['autoIndex']) is not bool:raise ValueError('自动索引选项无效')
    if cfg['autoIndex'] and not cfg['baseUrl']:raise ValueError('请先配置 Embedding 服务')
    if cfg['baseUrl'] and not cfg['model']:raise ValueError('请填写 Embedding 模型名称')
    return cfg

def embed(texts,cfg,*,attempts=3,check=lambda:None,root=None,reservation=None,reserved_tokens=None,on_response=None,purpose="document"):
    import httpx
    import project_embedding
    project_embedding.require_connection(cfg)
    if not cfg['baseUrl'] or not cfg['model']:raise ValueError('请先在设置 → Embedding 模型中配置 Embedding 服务')
    import embedding_limits as limits
    if root is None:
        import engine
        root=engine.ROOT
    limiter=limits.Limiter(root,cfg,check)
    # Pack whole input texts within batch and token budgets, never split a chunk.
    if reservation is not None and (len(texts)>cfg['batchSize'] or not reserved_tokens or reserved_tokens>limiter.cfg['tpm']):raise ValueError('调度批次超出已预留预算')
    groups=[];group=[]
    for text in texts:
        if reservation is None and limits.estimate([text])>limiter.cfg['tpm']:raise ValueError('单个文本的估算 token 数超过 TPM 限速设置，请提高 TPM；文本块未截断')
        if group and (len(group)>=cfg['batchSize'] or (reservation is None and limits.estimate(group+[text])>limiter.cfg['tpm'])):groups.append(group);group=[]
        group.append(text)
    if group:groups.append(group)
    if len(groups)>1:return [v for group in groups for v in embed(group,cfg,attempts=attempts,check=check,root=root,purpose=purpose)]
    if not texts:return []
    url=endpoint(cfg)
    headers={'Authorization':'Bearer '+cfg['apiKey']} if cfg.get('apiKey') else {}
    for attempt in range(attempts):
        try:
            reservation=reservation if attempt==0 and reservation else limiter.acquire(reserved_tokens or limits.estimate(texts))
            reserved_at=limiter.mark_dispatched(reservation)
            request_started=time.time()
            r=limits.post(url,headers,providers.payload(texts,cfg,purpose),cfg['timeout'],check)
            try:usage=r.json().get('usage',{})
            except (ValueError,AttributeError):usage={}
            if r.status_code==200:limiter.reconcile(reservation,usage)
            if on_response:
                on_response({'at':request_started,'reservedAt':reserved_at,'seconds':time.time()-request_started,'count':len(texts),'reserved':reserved_tokens or limits.estimate(texts),'status':r.status_code,'usage':usage})
            if r.status_code==429 or r.status_code>=500:
                delay=limits.retry_after(r.headers.get('Retry-After'),2**attempt)
                limiter.cooldown(delay)
                if attempt<attempts-1:limits.wait(delay,check);continue
                reason='请求限流或配额不足' if r.status_code==429 else '服务端异常，请稍后重试'
                raise limits.TransientError(f'Embedding HTTP {r.status_code}：{reason}',kind='rate_limit' if r.status_code==429 else 'service',retry_after=delay)
            if r.status_code!=200:
                reason={401:'API Key 无效或已失效',403:'服务拒绝访问，请检查模型权限',404:'接口或模型不存在，请检查 Base URL 与模型名称',429:'请求限流或配额不足'}.get(r.status_code,'服务端异常，请稍后重试' if r.status_code>=500 else '请检查模型、输入长度与请求配置')
                raise ValueError(f'Embedding HTTP {r.status_code}：{reason}')
            try:payload=r.json()
            except ValueError:raise ValueError('Embedding 返回了非 JSON 内容，请确认地址是 API 接口而不是网页') from None
            data=payload.get('data') if isinstance(payload,dict) else None;result=[None]*len(texts)
            if not isinstance(data,list) or len(data)!=len(texts):raise ValueError('Embedding 返回数量不匹配')
            dimension=None
            for row in data:
                if not isinstance(row,dict):raise ValueError('Embedding 返回格式无效，data 中的条目应为对象')
                i=row.get('index');v=row.get('embedding')
                if type(i) is not int or not 0<=i<len(texts) or result[i] is not None:raise ValueError('Embedding index 缺失、重复或越界')
                if not isinstance(v,list) or not v or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) or not any(v):raise ValueError('Embedding 向量为空、非数值、非有限数或全零')
                if dimension is not None and len(v)!=dimension:raise ValueError('Embedding 返回维度不一致')
                dimension=len(v);result[i]=v
            return result
        except httpx.TransportError as error:
            kind='timeout' if isinstance(error,httpx.TimeoutException) else 'network'
            if on_response:on_response({'at':request_started,'reservedAt':reserved_at,'seconds':time.time()-request_started,'count':len(texts),'reserved':reserved_tokens or limits.estimate(texts),'status':0,'usage':{},'errorKind':kind})
            if attempt==attempts-1:raise limits.TransientError('Embedding 网络错误或超时，请检查网络、服务地址与超时设置',kind=kind) from None
            limits.wait(2**attempt,check)
        finally:
            if reservation:limiter.finish(reservation)

def job_path(e):return files.base(e)/'metadata/vector-job.json'
def read_job(e):
    p=job_path(e);job=json.loads(p.read_text()) if p.exists() else None
    if job and job['state'] in ACTIVE:
        process=files.base(e)/'metadata/vector-process.json';info=json.loads(process.read_text()) if process.exists() else {}
        pid=job.get('pid') or (info.get('pid') if info.get('id')==job['id'] else None)
        if pid and not e.process_alive(pid):job.update(state='interrupted',error='索引进程已退出，重新建立索引会复用已成功生成的向量');e.write_json(p,job)
    return job

def start(e,a):
    import library_service
    library_service.check_owner(e,a)
    with storage.file_lock(files.base(e)/'metadata/vector-start.lock'):
        old=read_job(e)
        if old and old['state'] in ACTIVE:
            if a.get('requestId') and old.get('requestId')==a['requestId']:return {'id':old['id']}
            raise ValueError('已有索引任务正在运行')
        request=a.get('requestId');receipt=files.base(e)/'metadata'/('vector-request-'+e.ident(request)+'.json') if request else None
        if receipt and receipt.exists():return json.loads(receipt.read_text())
        cfg=config(e)
        if not cfg['baseUrl']:raise ValueError('请先配置 Embedding 服务；文本块浏览无需配置')
        import project_embedding
        project_embedding.require_connection(cfg)
        if a.get('tokenBudget','auto') not in ('auto','conservative','verified'):raise ValueError('无效的 token 预算模式')
        mode=a.get('mode','incremental')
        if mode not in ('incremental','rebuild','recompute'):raise ValueError('索引更新模式无效')
        if mode!='incremental' and a.get('confirm')!=e.PROJECT:raise ValueError('请确认索引重建范围')
        # Projects created before their first provider was configured must also
        # carry their model identity when moved into a fresh installation.
        project_embedding.bind(e,cfg,only_if_unbound=True)
        (files.base(e)/'metadata/index-cleared.json').unlink(missing_ok=True)
        chunks.sync(e);docs=chunks.documents(e,cache_profile(e,cfg));pmids=a.get('pmids')
        if pmids is not None:
            if not isinstance(pmids,list) or any(p not in {d['pmid'] for d in docs} for p in pmids):raise ValueError('只能索引当前 XML 中的文献')
            docs=[d for d in docs if d['pmid'] in pmids]
        docs=[d for d in docs if d['chunks']]
        if not docs:raise ValueError('没有可索引的文本：请完成全文转换，或检查摘要及最小分块长度')
        job={'tokenBudget':a.get('tokenBudget','auto'),'adaptive':bool(a.get('adaptive',cfg.get('adaptive',False))),'id':uuid.uuid4().hex,'state':'queued','project':e.PROJECT,'profile':cache_profile(e,cfg),'config':public(cfg),'pmids':[d['pmid'] for d in docs],'created':time.time(),'owner':a.get('owner',0),'requestId':request,'mode':mode,'completed':0,'failed':0,'skipped':0,'current':'','items':[]}
        out=files.folder(e,'logs/vectorization-'+job['id']);job['logPath']=str(out);e.write_json(job_path(e),job)
        env={**os.environ,'SCHOLARNOTELM_ROOT':str(e.ROOT),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(e.ROOT/'tmp'),'TEMP':str(e.ROOT/'tmp'),'TMP':str(e.ROOT/'tmp')}
        python=e.ROOT/('runtimes/marker/Scripts/python.exe' if os.name=='nt' else 'runtimes/marker/bin/python')
        try:
            with (out/'worker.log').open('ab') as log:
                proc=subprocess.Popen([str(python),str(e.ROOT/'services/vectors/worker.py'),'--project',e.PROJECT,'--job',job['id']],env=env,cwd=e.ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}))
            e.write_json(files.base(e)/'metadata/vector-process.json',{'id':job['id'],'pid':proc.pid})
        except Exception:
            job.update(state='failed',error='无法启动向量化工作进程');e.write_json(job_path(e),job);raise
        result={'id':job['id'],'count':len(docs)}
        if receipt:e.write_json(receipt,result)
        return result

@contextmanager
def index_lock(e):
    # Serializes the index worker with index clearing; searches read SQLite and need no lock.
    deadline=time.monotonic()+10
    while True:
        guard=storage.file_lock(files.base(e)/'metadata/vector-index.lock')
        try:guard.__enter__();break
        except ValueError:
            if time.monotonic()>=deadline:raise ValueError('索引正在建立或清空，请稍后重试；文本块浏览和关键词检索仍可使用') from None
            time.sleep(.05)
    try:yield
    finally:guard.__exit__(None,None,None)

def publish_document(e,cfg,pid,doc,check):
    """Mark a document indexed once every chunk has a cached vector; recall reads that cache directly."""
    p=doc['pmid'];check()
    with chunks.connect(e) as c:
        records=chunks.records_for(c,doc['version'],doc['metadata']);input_hash=chunks.input_signature(records)
        cached={r[0] for r in c.execute('SELECT e.input_hash FROM embeddings e JOIN embedding_owners o ON o.profile=e.profile AND o.input_hash=e.input_hash WHERE e.profile=? AND o.pmid=?',(pid,p))}
    if any(chunks.digest(chunks.embedding_text(r)) not in cached for r in records):raise ValueError('文献向量尚未齐全')
    chunks.sync(e,[p],reconcile=False)
    current=next(iter(chunks.documents(e,pid,pmid=p)),None)
    if not current or current['version']!=doc['version']:raise ValueError('转换期间文献版本或纳入集合已改变，请重新索引')
    with files.lock(e),chunks.connect(e) as c:
        import artifact_state
        if p not in (files.current(e) or set()) or artifact_state.epoch(e,p)!=doc['metadata'].get('rebuildEpoch',0):raise ValueError('文献已移出或重新纳入，索引结果未发布')
        now=chunks.records_for(c,current['version'],current['metadata'])
        if chunks.input_signature(now)!=input_hash or chunks.metadata_signature(current['metadata'])!=chunks.metadata_signature(doc['metadata']):raise ValueError('文献信息已改变，请重新索引')
        c.execute('INSERT OR REPLACE INTO indexed VALUES(?,?,?,?)',(pid,p,doc['version'],input_hash))
        c.execute('INSERT OR REPLACE INTO indexed_metadata VALUES(?,?,?)',(pid,p,chunks.metadata_signature(current['metadata'])))
    check()
    return {'pmid':p,'state':'success','chunks':len(records)}

def run(e,job_id):
    job=read_job(e)
    if not job or job['id']!=job_id:raise ValueError('索引任务已被替换')
    cfg=config(e);pid=job['profile'];out=Path(job['logPath'])
    def save():
        e.write_json(job_path(e),job);e.write_json(out/'report.json',job);e.atomic(out/'report.txt',json.dumps(job,ensure_ascii=False,indent=2))
    def stopped():return (files.base(e)/'metadata'/('vector-stop-'+job_id)).exists() or (job.get('owner') and not e.process_alive(job['owner']))
    job.update(state='running',pid=os.getpid());save()
    try:
        with storage.file_lock(files.base(e)/'metadata/vector-worker.lock'),index_lock(e),storage.file_lock(e.ROOT/'config/storage.lock',shared=True):
            import project_embedding
            project_embedding.require_connection(cfg)
            if pid not in profile_aliases(cfg):raise ValueError('Embedding 配置已改变，请重新启动索引')
            if job.get('mode') in ('rebuild','recompute'):
                with chunks.connect(e) as c:
                    c.execute('DELETE FROM indexed WHERE profile=?',(pid,));c.execute('DELETE FROM indexed_metadata WHERE profile=?',(pid,))
                    if job['mode']=='recompute':
                        c.execute('DELETE FROM embeddings WHERE profile=?',(pid,));c.execute('DELETE FROM embedding_owners WHERE profile=?',(pid,))
            chunks.sync(e)
            initial={d['pmid']:d for d in chunks.documents(e,pid) if d['pmid'] in job['pmids']}
            with chunks.connect(e) as db:
                wanted_all={chunks.digest(r[0]) for d in initial.values() for r in db.execute('SELECT text FROM chunks WHERE version=?',(d['version'],))}
                ready_hashes={r[0] for r in db.execute('SELECT input_hash FROM embeddings WHERE profile=?',(pid,))}&wanted_all
            job['vectorProgress']={'completed':len(ready_hashes),'total':len(wanted_all)};save()
            handled=set()
            def check_job():
                if stopped():raise InterruptedError('索引已停止')
            if job.get('adaptive'):
                import adaptive_embedding
                pending_writes={}
                def collect_writes(wait=False):
                    ready,_=concurrent.futures.wait(pending_writes,timeout=.05 if wait else 0,return_when=concurrent.futures.FIRST_COMPLETED) if pending_writes else ([],[])
                    for future in ready:
                        p=pending_writes.pop(future)
                        try:
                            result=future.result();job['completed']+=1
                        except InterruptedError:raise
                        except Exception as ex:
                            result={'pmid':p,'state':'failed','error':str(ex)[:800]};job['failed']+=1
                        job['items'].append(result);handled.add(p)
                    if ready:save()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as writer:
                    def ready_document(p):
                        check_job();doc=initial[p]
                        if doc['indexed'] and doc.get('metadataReady'):
                            job['skipped']+=1;job['items'].append({'pmid':p,'state':'skipped'});handled.add(p);return
                        while len(pending_writes)>=8:check_job();collect_writes(True)
                        def write():
                            began=time.monotonic();result=publish_document(e,cfg,pid,doc,check_job)
                            return {**result,'seconds':round(time.monotonic()-began,2)}
                        pending_writes[writer.submit(write)]=p
                    def adaptive_progress(value):
                        collect_writes();job['adaptiveProgress']=value;job['embeddedChunks']=value['completed'];job['totalChunks']=value['total']
                        job['vectorProgress']={'completed':value['completed'],'total':value['total']};save()
                    adaptive_embedding.populate(e,cfg,job['pmids'],check_job,adaptive_progress,out,job.get('tokenBudget','auto'),on_ready=ready_document)
                    job['adaptiveProgress']['state']='publishing';save()
                    while pending_writes:
                        check_job();collect_writes(True)
                save()
            for p in job['pmids']:
                if p in handled:continue
                if stopped():job['state']='stopped';break
                job['current']=p;save();began=time.monotonic()
                try:
                    doc=initial.get(p)
                    if not doc or (doc['indexed'] and doc.get('metadataReady')):
                        job['skipped']+=1;job['items'].append({'pmid':p,'state':'skipped'});continue
                    with chunks.connect(e) as c:
                        records=chunks.records_for(c,doc['version'],doc['metadata']);input_hash=chunks.input_signature(records)
                        wanted={chunks.digest(chunks.embedding_text(r)):chunks.embedding_text(r) for r in records}
                        cached={r['input_hash']:list(struct.unpack('<'+'f'*r['dimension'],r['vector'])) for r in c.execute('SELECT e.* FROM embeddings e JOIN embedding_owners o ON o.profile=e.profile AND o.input_hash=e.input_hash WHERE e.profile=? AND o.pmid=?',(pid,p)) if r['input_hash'] in wanted}
                    pending=[(h,t) for h,t in wanted.items() if h not in cached];batch=cfg['batchSize'];groups=[pending[n:n+batch] for n in range(0,len(pending),batch)]
                    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg['concurrency']) as pool:
                        # Bound scheduled requests, allowing cancellation between waves.
                        for at in range(0,len(groups),cfg['concurrency']):
                            if stopped():break
                            futures={pool.submit(embed,[t for _,t in g],cfg):g for g in groups[at:at+cfg['concurrency']]}
                            errors=[]
                            for future in concurrent.futures.as_completed(futures):
                                try:values=future.result()
                                except Exception as ex:errors.append(ex);continue
                                g=futures[future]
                                with files.lock(e),chunks.connect(e) as c:
                                    import artifact_state
                                    if p not in (files.current(e) or set()) or artifact_state.epoch(e,p)!=doc['metadata'].get('rebuildEpoch',0):raise ValueError('文献已移出或重新纳入，旧请求结果不再保存')
                                    old=c.execute('SELECT dimension FROM profiles WHERE id=?',(pid,)).fetchone();dim=len(values[0])
                                    if old and old['dimension']!=dim:raise ValueError('模型返回维度发生变化，请更改模型版本标识并建立独立索引')
                                    c.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?)',(pid,dim,json.dumps(public(cfg))))
                                    for (h,_),v in zip(g,values):
                                        if len(v)!=dim:raise ValueError('向量维度不一致')
                                        c.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?)',(pid,h,dim,struct.pack('<'+'f'*dim,*v)));cached[h]=v
                                        c.execute('INSERT OR IGNORE INTO embedding_owners VALUES(?,?,?)',(pid,h,p))
                                ready_hashes.update(h for h,_ in g);job['vectorProgress']={'completed':len(ready_hashes),'total':len(wanted_all)}
                                job['embeddedChunks']=len(cached);job['totalChunks']=len(wanted);save()
                            if errors:raise errors[0]
                    if stopped():job['state']='stopped';break
                    publish_document(e,cfg,pid,doc,lambda:None)
                    job['completed']+=1;job['items'].append({'pmid':p,'state':'success','chunks':len(records),'newEmbeddings':len(pending),'seconds':round(time.monotonic()-began,2)})
                except Exception as ex:
                    job['failed']+=1;job['items'].append({'pmid':p,'state':'failed','error':str(ex)[:800]})
                finally:save()
            else:job['state']='done'
            e.write_json(chunks.base(e)/'manifest.json',{'profile':pid,'config':public(cfg),'splitter':chunks.SPLITTER,'updated':time.time()})
    except InterruptedError:job.update(state='stopped')
    except Exception as ex:job.update(state='failed',error=str(ex)[:800])
    finally:job.update(current='',finished=time.time());save()

def search(e,a):
    query=str(a.get('query','')).strip()
    if not query or len(query)>4000:raise ValueError('请输入 1–4000 字符的检索问题')
    cfg=config(e);method=a.get('method','semantic')
    if method not in ('semantic','keyword'):raise ValueError('检索模式无效')
    if method=='semantic':
        import project_embedding
        project_embedding.require_connection(cfg)
    pid=cache_profile(e,cfg);chunks.sync(e);docs=chunks.documents(e,pid)
    selected=a.get('pmid');kind=a.get('sourceKind','all')
    docs=[d for d in docs if (not selected or d['pmid']==selected) and (kind=='all' or d['sourceKind']==kind) and (method=='keyword' or d['indexed'])]
    if not docs:return {'results':[],'note':'所选范围没有可检索文本；语义检索需要先建立当前模型的索引'}
    records={}
    with chunks.connect(e) as c:
        for d in docs:
            for r in chunks.records_for(c,d['version'],d['metadata']):
                records[r['id']]=r
        eligible={cid for cid,r in records.items() if chunks.recall_allowed(r)}
        if not eligible:return {'results':[],'note':'所选范围没有符合召回条件的文本块'}
        scores={};distances={}
        if method!='keyword':
            q=embed([query],cfg,purpose='query')[0];saved=c.execute('SELECT dimension FROM profiles WHERE id=?',(pid,)).fetchone()
            if not saved or saved['dimension']!=len(q):raise ValueError('查询向量维度与索引不一致')
            # Cosine ranking over the SQLite vector cache, the same store review and QA recall read.
            # Pure Python keeps this debug search runnable in every runtime; ~10k chunks take well under a second.
            from array import array
            from heapq import nlargest
            from operator import mul
            wanted={cid:chunks.digest(chunks.embedding_text(records[cid])) for cid in records if cid in eligible}
            hashes=sorted(set(wanted.values()));vectors={}
            for at in range(0,len(hashes),500):
                part=hashes[at:at+500]
                vectors.update((r['input_hash'],r['vector']) for r in c.execute(f"SELECT input_hash,vector FROM embeddings WHERE profile=? AND input_hash IN ({','.join('?'*len(part))})",(pid,*part)))
            qnorm=math.sqrt(sum(x*x for x in q));similarity={}
            for cid,h in wanted.items():
                if h not in vectors or not qnorm:continue
                v=array('f',vectors[h]);norm=math.sqrt(sum(map(mul,v,v)))
                if norm:similarity[cid]=sum(map(mul,v,q))/(norm*qnorm)
            for rank,cid in enumerate(nlargest(60,similarity,key=similarity.get)):scores[cid]=1/(60+rank+1);distances[cid]=1-similarity[cid]
        if method=='keyword':
            # Literal text lookup: no ranking model and no remote request.
            needle=query.casefold().strip()
            for cid,r in records.items():
                if cid in eligible and needle and needle in r['text'].casefold():scores[cid]=1
        limit=min(30,max(1,int(a.get('limit',10))));results=[]
        for cid,score in sorted(scores.items(),key=lambda x:x[1],reverse=True)[:limit]:
            r=records[cid];m=r['metadata'];neighbors=[records[x] for x in (m['previousChunkId'],m['nextChunkId']) if x in records]
            results.append({**r,'score':score,'distance':distances.get(cid),'neighbors':[{'id':n['id'],'text':n['text'],'chunkIndex':n['metadata']['chunkIndex']} for n in neighbors]})
    # A remote embedding request can outlive an XML/Markdown edit. Recheck before returning evidence.
    chunks.sync(e);current={d['pmid']:d for d in chunks.documents(e,pid)}
    results=[r for r in results if r['metadata']['pmid'] in current and current[r['metadata']['pmid']]['version']==r['metadata']['documentVersion'] and (method=='keyword' or current[r['metadata']['pmid']]['indexed'])]
    report={'query':query,'profile':pid,'method':method,'created':time.time(),'results':results,'note':'查找原文在本地匹配文字；语义检索使用当前 Embedding 服务。'}
    e.write_json(files.folder(e,'logs/retrieval')/(uuid.uuid4().hex+'.json'),report);return report

def rpc(e,action,a):
    if action=='resource':
        import evidence_resources
        return evidence_resources.image_rpc(e,a.get('resourceId',''))
    if action=='progress':return {'job':read_job(e)}
    if action=='settings':return settings(e)
    if action=='profile.key':
        import embedding_profiles
        return {'apiKey':embedding_profiles.get(e,a.get('id'))['apiKey']}
    if action=='models':
        import embedding_profiles
        return embedding_profiles.models(e,a)
    if action=='project.bind':
        if not a.get('project'):raise ValueError('请选择要绑定模型的项目')
        import embedding_profiles,retrieval_settings,project_embedding
        cfg=embedding_profiles.get(e,a.get('id'))
        if not retrieval_settings.verified(e.ROOT,cfg):raise ValueError('请先测试该配置的连接')
        if read_job(e) and read_job(e).get('state') in ACTIVE:raise ValueError('请先停止当前索引任务')
        project_embedding.bind(e,cfg);return settings(e)
    if action=='profile.activate':
        import embedding_profiles,retrieval_settings
        cfg=embedding_profiles.get(e,a.get('id'))
        if not retrieval_settings.verified(e.ROOT,cfg):raise ValueError('请先测试该配置的连接')
        embedding_profiles.activate(e,cfg['id']);return settings(e)
    if action=='profile.delete':
        import embedding_profiles
        embedding_profiles.delete(e,a.get('id'));return settings(e)
    if action=='settings.save':
        import embedding_profiles
        pid=embedding_profiles.save(e,a);return {**settings(e),'savedProfile':pid}
    if action=='test':
        cfg=validated(e,a);text=a.get('testText',TEST_TEXT)
        if not isinstance(text,str) or not 1<=len(text.strip())<=1000:raise ValueError('测试文本需为 1–1000 个字符')
        began=time.monotonic();v=embed([text.strip()],cfg,attempts=1,root=e.ROOT)[0]
        import retrieval_settings
        retrieval_settings.mark_verified(e,cfg,len(v))
        return {'dimension':len(v),'seconds':round(time.monotonic()-began,2),'model':cfg['model'],'endpoint':endpoint(cfg),'inputChars':len(text.strip()),'vectors':1}
    if action=='start':return start(e,a)
    if action=='stop':
        job=read_job(e)
        if job and job['state'] in ACTIVE:e.atomic(files.base(e)/'metadata'/('vector-stop-'+job['id']),'stop')
        return {'ok':True}
    if action=='report':
        job=read_job(e)
        if not job:raise ValueError('尚无索引任务报告')
        path=files.base(e)/'logs'/('vectorization-'+e.ident(job['id']))
        if a.get('open'):return e.open_local(path)
        return {'path':str(path),'text':json.dumps(job,ensure_ascii=False,indent=2)}
    if action=='search':
        return search(e,a)
    if action=='auto':
        cfg=config(e)
        import project_embedding
        if project_embedding.connection(cfg)['state']!='ready':return {'state':'not_configured'}
        if not cfg['autoIndex'] or not cfg['baseUrl']:return {'state':'not_configured' if not cfg['baseUrl'] else 'disabled'}
        return {'state':'started',**start(e,a)}
    if action=='folder':return e.open_local(chunks.base(e))
    if action in ('status','documents','chunks','export') and chunks.cleared(e):
        if action=='documents':return {'documents':[]}
        if action!='status':raise ValueError('索引数据已清空，请先建立索引')
        import artifact_state,markdown_service
        articles,_=chunks.xml_articles(e);items=[];cfg=markdown_service.config(e)
        for p in articles:
            state=artifact_state.markdown_state(e,p,cfg)
            items.append({'pmid':p,'pdfState':state['pdfState'],'markdownState':state['markdownState'],'vectorState':'missing','sourceKind':'pending_fulltext' if state['pdf'] else 'pubmed_abstract'})
        return {**settings(e),'cleared':True,'metadataPending':0,'job':read_job(e),'documents':len(items),'readyDocuments':0,'chunks':0,'readyChunks':0,'eligibleDocuments':len(items),'items':items,'xmlFingerprint':''}
    if action in ('status','documents','chunks','export'):
        cfg=config(e)
        if action=='status':
            import status_cache
            docs=status_cache.documents(e,cache_profile(e,cfg))
        else:
            chunks.sync(e);docs=chunks.documents(e,cache_profile(e,cfg))
        if action=='status':return {**settings(e),'refreshing':any(d.get('refreshing') for d in docs),'metadataPending':sum(d['indexed'] and not d.get('metadataReady') for d in docs),'job':read_job(e),'documents':len(docs),'readyDocuments':sum(d['indexed'] for d in docs),'chunks':sum(d['chunks'] for d in docs),'readyChunks':sum(d['chunks'] for d in docs if d['indexed']),'eligibleDocuments':sum(bool(d['chunks']) for d in docs),'items':[{'pmid':d['pmid'],'pdfState':d['metadata'].get('pdfState','missing'),'markdownState':d['metadata'].get('markdownState','missing'),'vectorState':d['state'],'sourceKind':d['sourceKind']} for d in docs],'xmlFingerprint':chunks.digest((files.base(e)/'pubmed/current.xml').read_text()) if (files.base(e)/'pubmed/current.xml').exists() else ''}
        if action=='documents':return docs
        p=e.pmid(a['pmid']);doc=next((d for d in docs if d['pmid']==p),None)
        if not doc:raise ValueError('文献已不在当前 XML 中')
        with chunks.connect(e) as c:
            records=chunks.records_for(c,doc['version'],doc['metadata']);source=c.execute('SELECT text FROM documents WHERE version=?',(doc['version'],)).fetchone()['text'];segments=chunks.split(source)
        if action=='export':
            path=files.folder(e,'vectors/exports')/f'{p}.jsonl'
            e.atomic(path,''.join(json.dumps({k:v for k,v in r.items() if k!='resources'},ensure_ascii=False)+'\n' for r in records))
            return {'path':str(path),'count':len(records)}
        offset=max(0,int(a.get('offset',0)));limit=min(100,max(1,int(a.get('limit',30))))
        if a.get('ignored'):
            ignored=[s for s in segments if not s['accepted']];return {'document':doc,'total':len(ignored),'items':ignored[offset:offset+limit],'ignoredCount':len(ignored),'source':source if a.get('includeSource') else None}
        return {'document':doc,'total':len(records),'items':records[offset:offset+limit],'ignoredCount':sum(not s['accepted'] for s in segments),'source':source if a.get('includeSource') else None}
    raise ValueError('未知向量化操作')
