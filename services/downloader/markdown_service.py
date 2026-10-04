"""Lightweight RPC and durable jobs for the separate local Marker runtime."""
import hashlib,json,os,subprocess,time,uuid
from pathlib import Path
import corpus_files,storage,markdown_cleaning,conversion_config as conversion

DEFAULTS={'device':'auto','badrCleanup':True,'cleaningMode':'references-v1','removeLines':[],'pdftextWorkers':'auto'}
MODELS={'layout':'layout/2025_02_18','texify':'texify/2025_02_18','recognition':'text_recognition/2025_02_18','table_rec':'table_recognition/2025_02_18','detection':'text_detection/2025_02_28','inline_detection':'inline_math_detection/2025_02_24','ocr_error':'ocr_error_detection/2025_02_18'}

def runtime(root):return root/('runtimes/marker/Scripts/python.exe' if os.name=='nt' else 'runtimes/marker/bin/python')
def config(e):
    path=e.ROOT/'config/markdown.json'
    project=corpus_files.base(e)/'metadata/conversion-settings.json'
    saved={**(json.loads(path.read_text()) if path.exists() else {}),**(json.loads(project.read_text()) if project.exists() else {})}
    return {**DEFAULTS,**{k:saved[k] for k in ('device','pdftextWorkers') if k in saved},'engine':'marker'}

def readiness(e):
    missing=[]
    for name,sub in MODELS.items():
        p=e.ROOT/'models/marker'/sub
        if not (p/'config.json').is_file() or not any(p.glob('*.safetensors')):missing.append(name)
    if not (e.ROOT/'services/marker/vendor/static/fonts/GoNotoCurrent-Regular.ttf').is_file():missing.append('本地字体')
    marker={'ready':runtime(e.ROOT).is_file() and not missing,'runtime':str(runtime(e.ROOT)),'models':str(e.ROOT/'models/marker'),'missing':missing,'label':'Marker 1.6.0','backend':'本地 · 关闭 OCR'}
    return {**marker,'config':config(e)}

def job_path(e):return corpus_files.base(e)/'metadata/markdown-job.json'
def read_job(e):
    path=job_path(e)
    value=json.loads(path.read_text()) if path.exists() else None
    if value and not value.get('pid'):
        process=corpus_files.base(e)/'metadata/markdown-process.json'
        info=json.loads(process.read_text()) if process.exists() else {}
        if info.get('id')==value['id']:value['pid']=info.get('pid')
    if value and value['state'] in ('queued','running','stopping') and value.get('pid') and not e.process_alive(value['pid']):
        value.update(state='interrupted',error='转换进程已退出，可以重新转换；已完成的 Markdown 会复用。')
        e.write_json(path,value)
    return value

def ensure_idle(e):
    job=read_job(e)
    if job and job['state'] in ('queued','running','stopping'):raise ValueError('请先等待或停止当前 Markdown 转换')

def text_workers(value,pages):
    if value!='auto' and (type(value) is not int or value not in (1,2,4,8,16)):
        raise ValueError('文字提取 worker 必须为自动、1、2、4、8 或 16')
    requested=(4 if pages>=40 else 1) if value=='auto' else value
    return requested,max(1,min(requested,pages//10))

def signature(cfg):
    # Reading old settings migrates in memory only. Execution parallelism never
    # changes the signature; old unversioned BADR outputs must become stale.
    cfg={**DEFAULTS,**cfg}
    # Preserve every existing Marker signature when merely adding engine choices.
    values={k:v for k,v in cfg.items() if k in conversion.MARKER_KEYS and k!='pdftextWorkers'}
    return hashlib.sha256(json.dumps({**values,'cleaningVersion':cleaning_version(cfg),'paragraphVersion':markdown_cleaning.PARAGRAPH_VERSION},sort_keys=True).encode()).hexdigest()

def cleaning_version(cfg):return 'references-only-v2'

def clean(text,cfg=None):
    import markdown_references
    cleaned,report=markdown_references.analyze(text,article_citations=True)
    return cleaned,[{**s,'text':text[s['charStart']:s['charEnd']],'rule':'R01_references','ruleId':'R01_references','ruleVersion':'references-only-v2'} for s in report['removed']]

def status(e):
    with corpus_files.lock(e):return status_locked(e)

def status_locked(e):
    sync=corpus_files.reconcile_locked(e);ids=corpus_files.current(e) or set();base=corpus_files.base(e);cfg=config(e);items=[]
    import artifact_state
    fallbacks=artifact_state.abstract_fallbacks(e)
    for p in sorted(ids,key=int):
        item=artifact_state.markdown_state(e,p,cfg)
        item['abstractFallback']=p in fallbacks and item['pdfState']=='missing'
        item['sourceReady']=item['pdf'] or item['abstractFallback']
        items.append(item)
    return {**readiness(e),'job':read_job(e),'items':items,'files':sync,'downloadStatus':artifact_state.download_status(e,items),'abstractCount':sum(i['abstractFallback'] for i in items),'sourceReadyCount':sum(i['sourceReady'] for i in items),'pdfCount':sum(i['pdf'] for i in items),'markdownCount':sum(i['ready'] for i in items),'latestCount':sum(i['markdownState']=='latest' and not i['needsConversion'] for i in items)}

def rpc(e,action,a):
    if action=='settings':return readiness(e)
    if action=='settings.save':
        ensure_idle(e)
        cfg=config(e)
        workers=a.get('pdftextWorkers',cfg['pdftextWorkers']);text_workers(workers,40)
        if a.get('device',cfg['device']) not in ('auto','cpu','mps','cuda'):raise ValueError('设备选项无效')
        cfg.update(pdftextWorkers=workers,device=a.get('device',cfg['device']))
        path=corpus_files.base(e)/'metadata/conversion-settings.json' if a.get('project') else e.ROOT/'config/markdown.json'
        e.write_json(path,cfg);return readiness(e)
    if action=='status':return status(e)
    if action=='reconcile':
        ensure_idle(e)
        if e.rows("SELECT id FROM batches WHERE project=? AND state IN ('queued','running','paused')",(e.PROJECT,)):raise ValueError('请在下载完成后更新本地文件')
        with corpus_files.lock(e):
            (corpus_files.base(e)/'metadata/pdf-cleared.json').unlink(missing_ok=True)
            result=corpus_files.reconcile_locked(e)
            result.update(corpus_files.register_local_pdfs(e))
            result.update(corpus_files.update_missing_pdf_report_locked(e))
        import vector_chunks
        vector_chunks.sync(e)
        return result
    if action=='open':
        p=e.pmid(a['pmid']);ids=corpus_files.current(e) or set()
        if p not in ids:raise ValueError('文献已不在当前集合')
        path=corpus_files.base(e)/('markdown/raw' if a.get('raw') else 'markdown')/f'{p}.md'
        if not path.is_file():raise ValueError('尚无全文 Markdown')
        return e.open_local(path)
    if action=='report':
        job=read_job(e)
        if not job:raise ValueError('尚无转换报告')
        return e.open_local(corpus_files.base(e)/'logs'/('markdown-'+e.ident(job['id'])))
    if action=='folder':return e.open_local(corpus_files.folder(e,'pdf/redundant' if a.get('redundant') else 'markdown'))
    if action=='stop':
        job=read_job(e)
        if job and job['state'] in ('queued','running','stopping'):
            e.atomic(corpus_files.base(e)/'metadata'/('markdown-stop-'+job['id']),'stop')
        return {'ok':True}
    if action=='start':
        import library_service
        library_service.check_owner(e,a)
        with storage.file_lock(corpus_files.base(e)/'metadata/markdown-start.lock'):
            request_id=a.get('requestId')
            receipt=corpus_files.base(e)/'metadata'/('markdown-request-'+e.ident(request_id)+'.json') if request_id else None
            if receipt and receipt.exists():return json.loads(receipt.read_text())
            existing=read_job(e)
            if request_id and existing and existing.get('requestId')==request_id:
                result={'id':existing['id'],'count':len(existing['pmids']),'pid':existing.get('pid')}
                e.write_json(receipt,result);return result
            if not request_id and any(json.loads(b['config']).get('convertAfter') for b in e.rows("SELECT config FROM batches WHERE state IN ('queued','running','paused')")):
                raise ValueError('下载并转换任务尚未结束，请先在任务中心完成或取消下载')
            ensure_idle(e);corpus_files.reconcile(e)
            mode=a.get('mode','convert')
            if mode not in ('convert','clean'):raise ValueError('转换操作无效')
            if mode=='convert' and not readiness(e)['ready']:raise ValueError('所选转换引擎的本地运行时或模型不完整')
            ids=corpus_files.current(e)
            if ids is None:raise ValueError('请先生成当前 PubMed XML')
            selected=a.get('pmids')
            if selected is not None:
                if not isinstance(selected,list) or any(e.pmid(x) not in ids for x in selected):raise ValueError('请选择当前 XML 中的文献')
                ids=ids & set(map(str,selected))
            folder='pdf' if mode=='convert' else 'markdown/raw';ext='pdf' if mode=='convert' else 'md'
            papers=sorted([p for p in ids if (corpus_files.base(e)/folder/f'{p}.{ext}').is_file()],key=int)
            if not papers:raise ValueError('没有可转换的 PDF' if mode=='convert' else '没有可重新清洗的原始 Markdown')
            job={'id':uuid.uuid4().hex,'project':e.PROJECT,'state':'queued','mode':mode,'pmids':papers,'config':config(e),'created':time.time(),'pid':None,'owner':a.get('owner',0),'completed':0,'failed':0,'skipped':0,'current':'','items':[],'requestId':request_id,'indexAfter':bool(a.get('indexAfter',False)),'force':bool(a.get('force',False)),'replaceEdited':bool(a.get('replaceEdited',False))}
            e.write_json(job_path(e),job)
            outdir=corpus_files.folder(e,'logs/markdown-'+job['id']);job['logPath']=str(outdir);e.write_json(job_path(e),job)
            env={**os.environ,'SCHOLARNOTELM_ROOT':str(e.ROOT),'PYTHONUNBUFFERED':'1','PYTHONUTF8':'1','TMPDIR':str(e.ROOT/'tmp'),'TEMP':str(e.ROOT/'tmp'),'TMP':str(e.ROOT/'tmp')}
            kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NO_WINDOW}
            try:
                python=runtime(e.ROOT)
                with (outdir/'conversion.log').open('ab') as out:
                    child=subprocess.Popen([str(python),str(e.ROOT/'services/marker/worker.py'),'--project',e.PROJECT,'--job',job['id']],cwd=e.ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=out,**kwargs)
                e.write_json(corpus_files.base(e)/'metadata/markdown-process.json',{'id':job['id'],'pid':child.pid})
                # Worker owns state from here; do not overwrite its first progress update.
                result={'id':job['id'],'count':len(papers),'pid':child.pid}
                if receipt:e.write_json(receipt,result)
                return result
            except Exception as ex:
                job.update(state='failed',error=str(ex));e.write_json(job_path(e),job);raise
    raise ValueError('未知 Markdown 操作')
