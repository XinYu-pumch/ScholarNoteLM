"""Resumable review writing, evidence scopes and deterministic tree assembly."""
import llm_provider
import compact_io
import content_language as lang
import review_content
import review_manuscripts as manuscripts
import asyncio,hashlib,html,json,os,re,subprocess,time,uuid,zipfile
from pathlib import Path
import retrieval_settings,review_format,review_bundle,evidence_resources as resources
import storage,review_service as outline,vector_chunks as chunks,review_retrieval as retrieval
from review_llm import chat,object_json,Cancelled
from review_materials import Guard,InputsChanged

DEFAULTS={'concurrency':3,'topK':7,'language':'中文','requirements':'','profileId':'','model':'','contextChars':90000,'limitContext':False}
ACTIVE={'queued','running','stopping'}
SYSTEM=review_bundle.SYSTEM

def config(path,data=None):
    saved=outline.read(path/'writing-settings.json',{});cfg={**DEFAULTS,**{k:v for k,v in saved.items() if k in DEFAULTS}}
    if data is not None:
        for key in DEFAULTS:
            if key in data:cfg[key]=data[key]
    for k in ('concurrency','topK'):
        if type(cfg[k]) is not int or cfg[k]<1:raise ValueError(f'{k} 必须为正整数')
    if type(cfg['limitContext']) is not bool:raise ValueError('请求预算开关必须为布尔值')
    for k,lo,hi in [('contextChars',12000,500000)]:
        if type(cfg[k]) is not int or not lo<=cfg[k]<=hi:raise ValueError(f'{k} 必须在 {lo}–{hi} 之间')
    for k,limit in [('requirements',15000),('language',30),('profileId',200),('model',500)]:cfg[k]=outline.bounded(cfg[k],limit,k)
    manifest=outline.read(path/'review.json',{})
    if 'contentLanguage' in manifest:
        cfg['language']=lang.label(manifest['contentLanguage']);cfg['promptVersion']=manifest.get('promptVersion',lang.VERSION)
    return cfg

def tree_units(rows):
    children={r['id']:[] for r in rows};by_serial={r['serial']:r for r in rows};parents={}
    for row in rows:
        parent=by_serial.get(row['serial'].rsplit('.',1)[0]) if '.' in row['serial'] else None
        parents[row['id']]=parent
        if parent:children[parent['id']].append(row)
    result=[]
    for row in rows:
        direct=children[row['id']];parent=parents[row['id']]
        siblings=children[parent['id']] if parent else [r for r in rows if parents[r['id']] is None]
        mixed=any(children[s['id']] for s in siblings) and any(not children[s['id']] for s in siblings)
        leaves=direct if direct and all(not children[r['id']] for r in direct) else [row] if not direct and (parent is None or mixed) else []
        if leaves:
            ancestors=[];p=parent
            while p:ancestors.insert(0,p);p=parents[p['id']]
            result.append({'id':row['id'],'serial':row['serial'],'title':row['title'],'nodes':[row]+[r for r in leaves if r['id']!=row['id']],'leaves':leaves,'ancestors':ancestors,'siblings':[r for r in siblings if r['id']!=row['id']]})
    expected={r['id'] for r in rows if not children[r['id']]}
    actual=[r['id'] for u in result for r in u['leaves']]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('终末标题未被准确分配，请检查大纲结构')
    return result

def source_signature(e):
    import artifact_state,markdown_service,corpus_files
    articles,_=chunks.xml_articles(e);cfg=markdown_service.config(e)
    # Engine preferences do not change published evidence until conversion succeeds.
    values=[chunks.SPLITTER,chunks.TEMPLATE,markdown_service.signature({**cfg,'engine':'marker'})]
    generation=outline.read(corpus_files.base(e)/'metadata/index-generation.json')
    if generation:values.append(generation)
    for pmid,article in sorted(articles.items()):
        state=artifact_state.markdown_state(e,pmid,cfg)
        values.append([{k:v for k,v in article.items() if k not in ('publicationDate','publicationDates')},{k:state[k] for k in ('pdfSha256','markdownSha256','rawSha256','markdownState','pdfState')},artifact_state.epoch(e,pmid),chunks.source(e,pmid,article)[1].get('resourceFingerprint')])
    return chunks.digest(values)

def job(e,name):
    path=outline.work(e,name)/'writing-job.json';j=outline.read(path,{})
    if j.get('state') in ACTIVE and ((j.get('pid') and not e.process_alive(j['pid'])) or (not j.get('pid') and time.time()-j.get('created',time.time())>30)):
        stopped=j['state']=='stopping'
        for item in j.get('items',{}).values():
            if item.get('state') not in ('done','failed'):item.update(state='cancelled' if stopped else 'failed',error='撰写进程已结束')
        j.update(state='cancelled' if stopped else 'failed',error='撰写进程已结束；可继续本轮，复用已完成部分',**progress_counts(j))
        e.write_json(path,j)
        if re.fullmatch('[a-f0-9]{32}',j.get('token','')):e.write_json(path.parent/'logs'/j['token']/'result.json',j)
    return j

def ensure_idle(e,name):
    if job(e,name).get('state') in ACTIVE:raise ValueError('请先取消或等待当前综述撰写完成')

def rows_at(e,path):
    csvpath=path/'outline.csv'
    if not csvpath.exists():return []
    return outline.nodes(e,path,outline.parse_csv(csvpath.read_text(encoding='utf8')))

# 'sendTemperature' is retired but stays in the key list so existing signatures remain valid.
def legacy_profile_signature(p):return chunks.digest(llm_provider.signature_fields(p,('id','model','endpoint','temperature','sendTemperature','visionModels')))
def profile_signature(p):
    # Preserve the existing fields and singleton/absent hashes. Only the selected
    # model's image capability affects review_bundle.messages/decode.
    vision=[p['model']] if p.get('model') in (p.get('visionModels') or []) else None
    return legacy_profile_signature({**p,'visionModels':vision})

def compatible_profile_signatures(p):
    # Old artifacts contain only a hash, not the original profile fields. Accept
    # exact legacy hashes; never ignore model/temperature/provider/effort changes.
    values={profile_signature(p),legacy_profile_signature(p)}
    if p.get('model') not in (p.get('visionModels') or []):
        values.add(legacy_profile_signature({**p,'visionModels':[]}))
    return values

def matches_unit_signature(saved,unit,cfg,topic,source,profiles,models,prompt_hash=''):
    return complete_unit(unit,saved) and any(saved.get('signature')==unit_signature(unit,cfg,topic,source,ps,models,prompt_hash) for ps in profiles)
def unit_signature(unit,cfg,topic,source,model_signature,models,prompt_hash=""):
    return chunks.digest([SYSTEM,review_format.FORMAT,review_bundle.VERSION,{k:v for k,v in unit.items() if k not in ('signature','promptSignature')},{k:v for k,v in cfg.items() if k not in ('concurrency','profileId','model') and (k!='limitContext' or v)},topic,source,model_signature,models,prompt_hash])

def read_artifact(path):
    try:
        value=outline.read(path,{})
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError,TypeError):return {}

def valid_retrieval(value):
    records=value.get('chunks')
    return (isinstance(records,list) and bool(records) and all(isinstance(r,dict) and r.get('id') and r.get('text') and isinstance(r.get('metadata'),dict) for r in records)
            and (not value.get('contentHash') or value['contentHash']==chunks.digest(records)))

def prepared(path,unit,expected=None):
    data=read_artifact(path/'prompts'/f'{unit["id"]}.json')
    try:
        if not data or any(not valid_retrieval(data.get('evidence',{}).get(n['id'],{})) for n in unit['leaves']):return None
        if data.get('format')!=review_bundle.VERSION or (expected is not None and data.get('signature')!=expected):return None
        if data.get('evidenceHash') and data['evidenceHash']!=chunks.digest(data['evidence']):return None
        if len(data.get('plans',[]))!=1:return None
        for plan in data['plans']:
            bundle=load_bundle(path,plan)
            review_bundle.hydrate(bundle,path/'review_parts')
            if bundle['unit']['unit_id']!=unit['serial']:return None
        if data.get('hash')!=chunks.digest(data['plans']):return None
    except (ValueError,KeyError,TypeError,AttributeError,OSError):return None
    return data

def load_bundle(path,plan):
    filename=plan.get('file','')
    if not re.fullmatch(r'prompt_section_[0-9.]+\.json',filename):raise ValueError('材料包文件名无效，请重新准备')
    raw=(path/'review_parts'/filename).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=plan['sha256']:raise ValueError('材料包已修改，请重新准备')
    return review_bundle.validate(json.loads(raw))

def prepare_unit(e,path,snapshot,unit,evidence):
    cfg=snapshot['config'];folder=path/'review_parts'
    bundle=review_bundle.make(snapshot,unit,evidence)
    review_bundle.validate(bundle)
    bundle=review_bundle.externalize(bundle,folder,storage.project_dir(e.ROOT,e.PROJECT),e.atomic)
    messages=review_bundle.messages(bundle,folder,{})
    if cfg.get('limitContext',False) and sum(len(m['content']) for m in messages)>cfg['contextChars']:
        raise ValueError('联合写作单元超过请求字符预算；请提高或关闭预算，材料未截断，也未拆分子标题')
    filename=f'prompt_section_{unit["serial"]}.json';text=review_bundle.dumps(bundle)+'\n'
    e.atomic(folder/filename,text)
    # TXT is a derived preview. Only JSON and its hashed resources drive requests.
    e.atomic(folder/f'prompt_section_{unit["serial"]}.txt','[阅读预览 · 正式输入为同名 JSON]\n\n[SYSTEM]\n'+messages[0]['content']+'\n\n[USER]\n'+messages[1]['content'])
    manifest=[{'file':filename,'sha256':hashlib.sha256(text.encode()).hexdigest(),'unit':unit}]
    value={'format':review_bundle.VERSION,'signature':unit['promptSignature'],'plans':manifest,'evidence':evidence,'created':time.time(),'retrieval':snapshot.get('retrieval',retrieval_settings.snapshot(e.ROOT,e.PROJECT))}
    value['hash']=chunks.digest(manifest);value['evidenceHash']=chunks.digest(evidence)
    e.write_json(path/'prompts'/f'{unit["id"]}.json',value)
    return value

def saved_unit(path,unit):
    # Public artifacts are authoritative: a deleted section must not reappear from cache.
    target=path/'review_parts'/f'section_{unit["serial"]}.json'
    if not target.is_file():return {}
    cached=read_artifact(path/'sections'/f'{unit["id"]}.json')
    if not cached:return {}
    try:
        public=json.loads(target.read_text(encoding='utf8'))
        if public!=review_format.public_part(unit,cached['sections'],cached.get('evidence',{})):
            return {}  # Externally changed content must be regenerated/validated before publication.
    except (ValueError,KeyError,TypeError,OSError):return {}
    return cached

def complete_unit(unit,saved):
    sections=saved.get('sections',[])
    return (len(sections)==len(unit['nodes']) and
            {s.get('node_id') for s in sections}=={n['id'] for n in unit['nodes']} and
            all(isinstance(s.get('markdown'),str) and s['markdown'].strip() for s in sections))

def round_inputs(ctx,source,models,rcfg):
    frozen=ctx.get('materialSnapshot',{})
    return frozen.get('sourceSignature',source),frozen.get('modelsSignature',models),frozen.get('retrieval',rcfg)

def material_settings_changed(ctx,cfg,topic):
    return ctx.get('topic',topic)!=topic or any(cfg.get(k)!=ctx.get('config',{}).get(k,DEFAULTS.get(k)) for k in ('topK','requirements','language','limitContext','contextChars'))

def same_model(a,b):
    import vector_service as v
    if a.get('embeddingModel') and b.get('embeddingModel'):
        return v.profile(a['embeddingModel'])==v.profile(b['embeddingModel'])
    return a.get('embeddingFingerprint')==b.get('embeddingFingerprint')

def progress_counts(j):
    states=[i.get('state','pending') for i in j.get('items',{}).values()]
    result={'total':len(states),'completed':states.count('done'),'failed':states.count('failed'),
            'cancelled':states.count('cancelled'),'pending':states.count('pending')}
    result['running']=len(states)-sum(result[k] for k in ('completed','failed','cancelled','pending'))
    result['settled']=result['completed']+result['failed']+result['cancelled']
    return result

def status(e,name):
    path=outline.work(e,name);cfg=config(path);state=outline.vstate(e,name,'current');current_rows=rows_at(e,path);ctx=manuscripts.context(e,name);rows=ctx['rows'];units=tree_units(rows)
    outline_changed=manuscripts.fingerprint(current_rows)!=ctx['outlineHash']
    try:p=outline.profile(e,cfg['profileId'],cfg['model']);profiles=compatible_profile_signatures(p);model=p['model'];model_label=(p.get('name','')+'/' if p.get('name') else '')+model
    except ValueError:profiles=set();model='';model_label=''
    import status_cache
    live_source=status_cache.cached(e,'review.source-signature',lambda:source_signature(e));rcfg=retrieval_settings.snapshot(e.ROOT,e.PROJECT);live_models=retrieval.signature(e.ROOT,rcfg);source,models,material_cfg=round_inputs(ctx,live_source,live_models,rcfg);j=job(e,name);items=[];preparations={}
    for u in units:
        saved=saved_unit(path,u)
        pre=prepared(path,u,unit_signature(u,cfg,state.get('topic',''),source,'',models))
        preparations[u['id']]=pre
        latest=not outline_changed and matches_unit_signature(saved,u,cfg,state.get('topic',''),source,profiles,models,pre['hash'] if pre else '')
        live=j.get('items',{}).get(u['id'],{})
        phase='latest' if latest else 'outdated' if saved else 'pending'
        if j.get('state') in ACTIVE and live:phase=live.get('state',phase)
        elif live.get('state') in ('failed','cancelled'):phase=live['state']
        items.append({'id':u['id'],'serial':u['serial'],'title':u['title'],'nodes':[n['id'] for n in u['nodes']],'leafIds':[n['id'] for n in u['leaves']],'state':phase,'latest':latest,'promptReady':bool(pre) and not outline_changed,'hasContent':bool(saved),'error':live.get('error',''),'received':live.get('received',0),'reasoningCharacters':live.get('reasoningCharacters',0),'revision':chunks.digest([saved.get('created'),bool(saved),pre.get('hash') if pre else None,outline_changed])})
    preparation_count=0;shortfalls=0
    for u,item in zip(units,items):
        for n in u['leaves']:
            evidence=read_artifact(path/'retrieval'/f'{n["id"]}.json')
            if item['promptReady']:
                evidence=preparations[u['id']].get('evidence',{}).get(n['id'],{})
            valid=valid_retrieval(evidence) and evidence.get('query')==n['title'] and evidence.get('topK')==cfg['topK'] and same_model(evidence.get('retrieval',{}),material_cfg)
            if valid and not outline_changed:
                preparation_count+=1
                if len(evidence['chunks'])<cfg['topK']:shortfalls+=1
    ready=bool(items) and all(i['promptReady'] for i in items)
    incompatible=not same_model(material_cfg,rcfg) or source!=live_source
    if incompatible and not ready:preparation_count=0;shortfalls=0
    attempted=bool(j) or (path/'writing-round.json').exists() or any((path/'prompts').glob('*.json'))
    material_changed=bool(ctx.get('materialSnapshot')) and material_settings_changed(ctx,cfg,state.get('topic',''))
    prep_state='ready' if ready else 'stale' if outline_changed or material_changed or (attempted and incompatible) else 'partial' if attempted else 'idle'
    write_state='complete' if items and all(i['latest'] for i in items) else 'partial' if any(i['hasContent'] for i in items) or (j.get('mode')=='write' and j) else 'idle'
    stages={'preparation':{'state':prep_state,'completed':preparation_count,'total':sum(len(u['leaves']) for u in units),'shortfalls':shortfalls},
            'writing':{'state':write_state,'completed':sum(len(i['nodes']) for i in items if i['latest']),'total':sum(len(i['nodes']) for i in items)}}
    return {'stages':stages,'materialModel':material_cfg.get('embeddingModel',{}).get('model','') if ctx.get('materialSnapshot') else '','projectModel':rcfg.get('embeddingModel',{}).get('model',''),'materialModelChanged':not same_model(material_cfg,rcfg),'draftCount':len(manuscripts.listing(e,name,drafts=True)),'outlineChanged':outline_changed,'hasContent':any(i['hasContent'] for i in items),'currentOutlineCount':len(current_rows),'manuscriptCount':len(manuscripts.listing(e,name)),'config':cfg,'rows':rows,'units':items,'job':{**j,**progress_counts(j)},'fileRevision':chunks.digest([outline_changed,[(i['id'],i['revision']) for i in items]]),'model':model,'modelLabel':model_label,'runtimeReady':runtime(e,rcfg).is_file() and retrieval.ready(e.ROOT,rcfg),'retrieval':retrieval_settings.public(e),'effectiveCandidateK':retrieval_settings.effective(rcfg,cfg['topK']),'prepared':sum(i['promptReady'] for i in items),'latest':sum(i['latest'] for i in items),'total':len(items),'path':str(path)}

def runtime(e,cfg=None):
    cfg=cfg or retrieval_settings.read(e.ROOT);kind='retrieval'
    return e.ROOT/'runtimes'/kind/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def rpc(e,name,op,a):
    path=outline.work(e,name)
    if op=='manuscripts':return manuscripts.listing(e,name,drafts=bool(a.get('drafts')))
    if op=='manuscript':return manuscripts.preview(manuscripts.get(e,name,a.get('id')))
    if op=='manuscript.export':return manuscripts.export(e,name,a.get('format','md'),a.get('id'))
    if op=='activity':return {'state':job(e,name).get('state','idle')}
    if op=='status':return status(e,name)
    if op=='open-tasks':
        folder=path/'logs';folder.mkdir(parents=True,exist_ok=True);return e.open_local(folder)
    if op=='open-prompts':
        folder=path/'review_parts';folder.mkdir(parents=True,exist_ok=True);return e.open_local(folder)
    if op=='section':
        ident=a.get('nodeId','')
        if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('节点标识无效')
        units=tree_units(manuscripts.context(e,name)['rows']);u=next((u for u in units if ident in [n['id'] for n in u['nodes']]),None)
        if not u:return {'sections':[],'evidence':{}}
        saved=saved_unit(path,u)
        evidence={n['id']:read_artifact(path/'retrieval'/f'{n["id"]}.json') for n in u['leaves']}
        # Completed body must show its original evidence, even after a failed regeneration.
        selected_evidence=saved.get('evidence',evidence)
        shared=bool(saved.get('sections') and all(s.get('citationPoolVersion') in review_bundle.READ_VERSIONS for s in saved['sections'])) or (not saved and bool(prepared(path,u)))
        display=display_document(e,name,only_unit=u['id']) if saved else {}
        return {**saved,'sections':[display[s['node_id']] for s in saved.get('sections',[])],'evidence':selected_evidence,'unit':u,'sharedEvidence':review_bundle.display_records(u,selected_evidence) if shared else None}
    if op=='preview':
        md,state,body,evidence,refs,blocks=assemble(e,name,True)
        ordered=[{'type':'markdown','text':'# '+(manuscripts.context(e,name).get('topic') or name)}]
        if any(not u['latest'] for u in state['units']):ordered.append({'type':'markdown','text':'> 草稿：含尚未生成或待更新章节。'})
        for row in state['rows']:ordered.extend([{'type':'markdown','text':'#'*min(len(row['serial'].split('.')),6)+' '+row['serial']+' '+row['title']},*blocks.get(row['id'],[])])
        if refs:ordered.append({'type':'markdown','text':'## 参考文献\n\n'+'\n'.join('- PMID: '+p for p in sorted(refs,key=int))})
        return {'markdown':md,'displayBlocks':ordered}
    if op=='cancel':
        j=job(e,name)
        if j.get('state') in ACTIVE:j.update(state='stopping');e.write_json(path/'writing-job.json',j)
        return status(e,name)
    ensure_idle(e,name);outline.idle(outline.vstate(e,name,'current'))
    if op=='reset':
        if a.get('confirm') is not True:raise ValueError('请确认保存草稿并重置撰写')
        manuscripts.reset(e,name);return status(e,name)
    if op=='settings':
        e.write_json(path/'writing-settings.json',config(path,a));return status(e,name)
    if op=='export':return export(e,name,a.get('format','md'))
    if op not in ('start','prepare','prepare.resume','retry'):raise ValueError('未知综述撰写操作')
    mode='prepare' if op in ('prepare','prepare.resume') or (op=='retry' and job(e,name).get('mode')=='prepare') else 'write'
    cfg=config(path,a.get('config',{}));p=outline.profile(e,cfg['profileId'],cfg['model']) if mode=='write' else {};state=outline.vstate(e,name,'current')
    rcfg=retrieval_settings.snapshot(e.ROOT,e.PROJECT)
    rows=rows_at(e,path);units=tree_units(rows)
    if not units:raise ValueError('请先生成并保存综述大纲')
    if not state.get('topic','').strip():raise ValueError('请先填写并保存综述主题')
    if mode=='prepare' and (not runtime(e,rcfg).is_file() or not retrieval.ready(e.ROOT,rcfg)):raise ValueError('请先验证 Embedding 连接并检查检索运行环境')
    selected=a.get('unitIds')
    if op=='retry':
        current=status(e,name)
        selected=None  # Recompute missing/invalid artifacts, including interrupted and pending units.
        mode='prepare' if current['job'].get('mode')=='prepare' else 'write'
    if op=='prepare' and selected is not None:raise ValueError('新一轮准备须覆盖完整大纲')
    source=source_signature(e);models=retrieval.signature(e.ROOT,rcfg);ps=profile_signature(p);profiles=compatible_profile_signatures(p)
    ctx=manuscripts.context(e,name)
    if op=='prepare':
        if any(saved_unit(path,u).get('sections') for u in tree_units(ctx['rows'])) and a.get('confirm') is not True:
            raise ValueError('当前正文将先保存，请确认开始新一轮撰写')
        manuscripts.reset(e,name)
        ctx=manuscripts.new_round(e,name,rows,state['topic'],cfg)
        ctx['materialSnapshot']={'sourceSignature':source,'modelsSignature':models,'retrieval':rcfg}
        e.write_json(path/'writing-round.json',ctx)
    else:
        if manuscripts.fingerprint(rows)!=ctx['outlineHash']:
            raise ValueError('当前大纲与本轮撰写不一致，请准备新一轮撰写')
        rows=ctx['rows'];units=tree_units(rows)
        if not (path/'writing-round.json').exists():manuscripts.freeze(e,name)
    if op!='prepare':
        frozen_source,frozen_models,frozen_cfg=round_inputs(ctx,source,models,rcfg)
        if mode=='prepare' and (frozen_source!=source or not same_model(frozen_cfg,rcfg) or (ctx.get('materialSnapshot') and material_settings_changed(ctx,cfg,state['topic']))):
            raise ValueError('本轮材料来源或参数已变化，请恢复原设置或准备新一轮材料，不能混用不同模型的材料')
        source,models=frozen_source,frozen_models
        if mode=='write':rcfg=frozen_cfg
        # A new credential is verified live, but never changes the frozen artifact identity.
    if mode=='write' and any(not prepared(path,u,unit_signature(u,cfg,state['topic'],source,'',models)) for u in units):
        raise ValueError('请先为全部章节准备完整的写作材料（提示词）')
    if selected is not None and (not isinstance(selected,list) or not selected or any(i not in {u['id'] for u in units} for i in selected)):raise ValueError('选择的写作单元无效')
    e.write_json(path/'writing-settings.json',cfg)
    tasks=[]
    for u in units:
        u['promptSignature']=unit_signature(u,cfg,state['topic'],source,'',models)
        pre=prepared(path,u,u['promptSignature'])
        u['signature']=unit_signature(u,cfg,state['topic'],source,ps,models,pre['hash'] if pre else '')
        if selected is not None and u['id'] not in selected:continue
        if mode=='write' and not pre:raise ValueError('提示词尚未准备或已过期，请先准备新一轮撰写，或继续本轮准备')
        old=saved_unit(path,u)
        if selected is None and ((mode=='prepare' and pre) or (mode=='write' and matches_unit_signature(old,u,cfg,state['topic'],source,profiles,models,pre['hash'] if pre else ''))):continue
        tasks.append(u)
    if not tasks:return status(e,name)
    if mode=='write':manuscripts.save(e,name)
    token=uuid.uuid4().hex;run=path/'logs'/token;run.mkdir(parents=True)
    snapshot={'token':token,'created':time.time(),'topic':state['topic'],'config':cfg,'mode':mode,'retrieval':rcfg,'profileId':p.get('id',''),'model':p.get('model',''),'profileSignature':ps,'sourceSignature':source,'modelsSignature':models,'rows':rows,'tasks':tasks,'frozenMaterials':True,'sessionRound':ctx['id']}
    compact_io.write_json(e,run/'input.json',snapshot)
    j={'token':token,'state':'queued','created':time.time(),'updated':time.time(),'pid':0,'owner':a.get('owner',0),'total':len(tasks),'completed':0,'failed':0,'mode':mode,'phase':'准备提示词' if mode=='prepare' else '准备生成综述','items':{u['id']:{'state':'pending'} for u in tasks},'error':''}
    e.write_json(path/'writing-job.json',j)
    env={**os.environ,'SCHOLARNOTELM_ROOT':str(e.ROOT),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(e.ROOT/'tmp'),'TEMP':str(e.ROOT/'tmp'),'TMP':str(e.ROOT/'tmp')}
    try:
        with (run/'worker.log').open('ab') as out:
            proc=subprocess.Popen([str(runtime(e,rcfg)),str(e.ROOT/'services/downloader/review_write_worker.py'),'--project',e.PROJECT,'--review',name,'--token',token],cwd=e.ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=out,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}))
        # review_service.rpc already holds the project review lock here.
        current=outline.read(path/'writing-job.json',{})
        if current.get('token')==token:
            current['pid']=proc.pid;e.write_json(path/'writing-job.json',current)
    except Exception:
        j.update(state='failed',error='无法启动综述撰写进程')
        for item in j['items'].values():item.update(state='failed',error=j['error'])
        j.update(progress_counts(j));e.write_json(path/'writing-job.json',j);e.write_json(run/'result.json',j);raise ValueError(j['error']) from None
    return status(e,name)

def citations(text):
    ids=set()
    for m in re.finditer(r'PMID\s*[:：]\s*([\d\s,，、;；]+)',text,re.I):ids.update(re.findall(r'\d+',m[1]))
    return ids

def validate(value,unit,evidence):
    """Historical PMID output validator. New requests use review_bundle.decode."""
    sections=value.get('sections');expected={n['id'] for n in unit['nodes']}
    if not isinstance(sections,list) or any(not isinstance(s,dict) for s in sections):raise ValueError('正文 sections 格式无效')
    ids=[s.get('node_id') for s in sections]
    if any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)) or set(ids)!=expected:raise ValueError('返回章节有遗漏、重复或额外节点')
    errors={}
    for section in sections:
        text=section.get('markdown');ident=section['node_id']
        if not isinstance(text,str) or not text.strip():raise ValueError('正文不能为空')
        if re.search(r'^\s*#{1,6}\s',text,re.M):raise ValueError('正文重复了标题，应仅返回正文内容')
        allowed={r['metadata']['pmid'] for r in evidence.get(ident,{}).get('chunks',[])}
        bad=citations(text)-allowed
        if bad:errors[ident]=sorted(bad)
    return sections,errors

def safe_error(ex):
    return str(ex) if isinstance(ex,(ValueError,Cancelled)) else '任务失败，请检查本地运行时与日志后重试'

async def run(e,name,token,retriever_factory=None):
    path=outline.work(e,name);runpath=path/'logs'/token;snapshot=outline.read(runpath/'input.json');cfg=snapshot['config']
    mode=snapshot.get('mode','legacy');rcfg=snapshot.get('retrieval',retrieval_settings.snapshot(e.ROOT,e.PROJECT));candidate_k=retrieval_settings.effective(rcfg,cfg['topK'])
    def cancelled():
        j=outline.read(path/'writing-job.json',{})
        return j.get('token')!=token or j.get('state') not in ('queued','running') or bool(j.get('owner') and not e.process_alive(j['owner']))
    def check():
        # Called from HTTP polling, token callbacks and quota waits. Keep it
        # cancellation-only: synchronous corpus parsing blocks the event loop.
        if cancelled():raise Cancelled('已取消撰写，已完成正文保留')
    materials=Guard(e,(snapshot['sourceSignature'],True),
                    lambda:(source_signature(e),same_model(rcfg,retrieval_settings.snapshot(e.ROOT,e.PROJECT))))
    async def verify_materials():
        check()
        if mode=='prepare' or not snapshot.get('frozenMaterials'):await asyncio.to_thread(materials.verify)
        check()
    def chat_cancelled():
        check()
        return False
    def update(ident=None,**fields):
        with outline.lock(e):
            check();j=outline.read(path/'writing-job.json')
            if ident:
                j['items'][ident].update(fields)
                if fields.get('state') in ('done','failed'):j['items'][ident]['finished']=time.time()
                if fields.get('state')=='writing':j['items'][ident]['started']=time.time()
            else:j.update(fields)
            j.update(progress_counts(j));j['updated']=time.time();e.write_json(path/'writing-job.json',j)
            if 'state' in fields:e.write_json(runpath/'result.json',j)
    try:
        if mode not in ('prepare','write'):raise ValueError('旧任务使用不同的检索流程，请重新准备提示词')
        check();update(state='running',phase='准备当前文本块' if mode=='prepare' else '读取已保存的提示词')
        p=outline.profile(e,snapshot['profileId'],snapshot.get('model') or cfg.get('model')) if mode=='write' else {}
        if mode=='write' and snapshot['profileSignature'] not in compatible_profile_signatures(p):raise ValueError('模型配置已变化，请重新开始')
        records=await asyncio.to_thread(retrieval.corpus,e) if mode=='prepare' else []
        await verify_materials()
        corpus_sig=chunks.digest([snapshot['modelsSignature'],[(r['id'],chunks.embedding_text(r)) for r in records]])
        leaves={n['id']:n for u in snapshot['tasks'] for n in u['leaves']}
        queries={ident:n['title'] for ident,n in leaves.items()}
        # One global local-inference queue, with one model instance per run, across workspaces.
        guard=None;retriever=None;evidence_all={};writing_tasks=[];sem=asyncio.Semaphore(cfg['concurrency'])
        async def write_unit(unit,evidence):
            async with sem:
                try:
                    check();update(unit['id'],state='writing',error='')
                    pre=prepared(path,unit,unit['promptSignature'])
                    if not pre:raise ValueError('提示词缺失或发生变化，请重新准备')
                    plan=pre['plans'][0];bundle=load_bundle(path,plan)
                    # Assert the canonical pool still matches the immutable retrieval snapshot.
                    expected=review_bundle.make(snapshot,unit,evidence)
                    actual=review_bundle.hydrate(bundle,path/'review_parts')
                    if any(actual[k]!=expected[k] for k in ('unit','task','evidencePool','retrieval','outputContract')) or len(actual['resources'])!=len(expected['resources']):
                        raise ValueError('共享池与检索记录不一致，请重新准备')
                    for delivered,original in zip(actual['resources'],expected['resources']):
                        delivered=dict(delivered);original=dict(original);image_file=delivered.pop('imageFile',None)
                        original.pop('assetPath',None);sha=original.pop('assetSha256',None)
                        if delivered!=original or (image_file or {}).get('sha256')!=sha:raise ValueError('图表与冻结检索记录不一致，请重新准备')
                    request_profile=llm_provider.with_session(p,'writing',e.PROJECT,name,snapshot.get('sessionRound',snapshot['sourceSignature']),unit['id'])
                    messages=review_bundle.messages(bundle,path/'review_parts',p)
                    text_content=messages[-1]['content'];text_content=text_content[0]['text'] if isinstance(text_content,list) else text_content
                    if cfg.get('limitContext',False) and len(messages[0]['content'])+len(text_content)>cfg['contextChars']:
                        raise ValueError('联合写作单元超过请求字符预算；请提高或关闭预算')
                    stem=unit['id']+'-0'
                    compact_io.write_text(e,runpath/(stem+'.prompt.json'),json.dumps(messages,ensure_ascii=False,indent=2))
                    await verify_materials()
                    raw=await chat(request_profile,messages,chat_cancelled,lambda **kw:update(unit['id'],**kw));compact_io.write_text(e,runpath/(stem+'.response.txt'),raw)
                    update(unit['id'],state='validating')
                    try:
                        value=object_json(raw);sections,errors=review_bundle.decode(value,bundle,unit,p)
                    except ValueError as ex:
                        value=raw;sections=[];errors={'structure':[str(ex)]}
                    if errors:
                        serials={n['id']:n['serial'] for n in unit['nodes']}
                        repair=review_bundle.repair_messages(bundle,path/'review_parts',p,value,{serials.get(k,k):v for k,v in errors.items()})
                        compact_io.write_text(e,runpath/(stem+'.repair.prompt.json'),json.dumps(repair,ensure_ascii=False,indent=2))
                        await verify_materials()
                        fixed=await chat(request_profile,repair,chat_cancelled);compact_io.write_text(e,runpath/(stem+'.repair.response.txt'),fixed)
                        sections,errors=review_bundle.decode(object_json(fixed),bundle,unit,p)
                        if errors:raise ValueError('引用校验仍未通过：仅允许当前共享池中的证据 ID，父标题导语不能引用')
                    await verify_materials()
                    with outline.lock(e):
                        check();current=prepared(path,unit,unit['promptSignature'])
                        if not current or current['hash']!=pre['hash']:raise ValueError('生成期间材料包或资源发生变化，结果未发布，请重新准备')
                        value={'signature':unit['signature'],'unitId':unit['id'],'unit_id':unit['serial'],'sections':sections,'evidence':evidence,'created':time.time(),'run':token,'model':p['model'],'promptHash':pre['hash']}
                        e.write_json(path/'sections'/f'{unit["id"]}.json',value)
                        e.write_json(path/'review_parts'/f'section_{unit["serial"]}.json',review_format.public_part(unit,sections,evidence))
                    update(unit['id'],state='done')
                except (Cancelled,InputsChanged):raise
                except Exception as ex:update(unit['id'],state='failed',error=safe_error(ex))
        try:
            for unit in snapshot['tasks']:
                check();evidence={}
                try:
                    if mode=='write':
                        pre=prepared(path,unit,unit['promptSignature'])
                        if not pre:raise ValueError('提示词缺失或已过期，请重新准备')
                        writing_tasks.append(asyncio.create_task(write_unit(unit,pre['evidence'])));await asyncio.sleep(0);continue
                    update(unit['id'],state='retrieving',error='')
                    for node in unit['leaves']:
                        ident=node['id'];query=queries[ident];sig=chunks.digest([corpus_sig,query,candidate_k,cfg['topK']])
                        cached=read_artifact(path/'retrieval'/f'{ident}.json')
                        if cached.get('signature')==sig and valid_retrieval(cached):result=cached
                        else:
                            if retriever is None:
                                update(phase='准备召回模型')
                                factory=retriever_factory or retrieval.Retriever
                                retriever=await asyncio.to_thread(factory,e.ROOT,storage.project_dir(e.ROOT,e.PROJECT)/'vectors',records,check,lambda phase:update(phase=phase),**({} if retriever_factory else {'cfg':rcfg,'e':e}))
                            update(phase=f'检索 {node["serial"]} · {node["title"]}')
                            found=await asyncio.to_thread(retriever.retrieve,query,candidate_k,cfg['topK'])
                            await verify_materials()
                            if not found:raise ValueError('该标题未召回任何文本块，请检查文献后重试')
                            result={'signature':sig,'query':query,'sourceTitle':node['title'],'nodeId':ident,'chunks':found,'contentHash':chunks.digest(found),'retrieval':rcfg,'candidateK':candidate_k,'topK':cfg['topK'],'corpusSignature':corpus_sig,'created':time.time()}
                            e.write_json(path/'retrieval'/f'{ident}.json',result)
                        evidence[ident]=result;evidence_all[ident]=result
                    await verify_materials()
                    with outline.lock(e):
                        check();prepare_unit(e,path,snapshot,unit,evidence)
                    update(unit['id'],state='done');await asyncio.sleep(0)
                except (Cancelled,InputsChanged):raise
                except Exception as ex:update(unit['id'],state='failed',error=safe_error(ex))
            update(phase='生成正文 · 完成后逐项校验引用' if mode=='write' else '提示词准备完成');await asyncio.gather(*writing_tasks)
        finally:
            if cancelled():
                for task in writing_tasks:task.cancel()
            await asyncio.gather(*writing_tasks,return_exceptions=True)
            retriever=None
            import gc
            gc.collect()
            if guard:guard.__exit__(None,None,None)
        check();j=outline.read(path/'writing-job.json');failed=sum(i['state']=='failed' for i in j['items'].values());completed=sum(i['state']=='done' for i in j['items'].values())
        update(state='partial' if failed else 'done',completed=completed,failed=failed,phase='部分任务失败，可继续重试' if failed else '提示词准备完成' if mode=='prepare' else '综述撰写完成')
    except BaseException as ex:
        with outline.lock(e):
            j=outline.read(path/'writing-job.json',{})
            if j.get('token')==token:
                stopped=isinstance(ex,(Cancelled,asyncio.CancelledError)) or j.get('state')=='stopping'
                for item in j.get('items',{}).values():
                    if item['state'] not in ('done','failed'):item['state']='cancelled' if stopped else 'failed'
                j.update(state='cancelled' if stopped else 'failed',error=safe_error(ex),completed=sum(i['state']=='done' for i in j['items'].values()),failed=sum(i['state']=='failed' for i in j['items'].values()),updated=time.time())
                j.update(progress_counts(j));e.write_json(path/'writing-job.json',j)
                e.write_json(runpath/'result.json',j)
        if not isinstance(ex,(Exception,asyncio.CancelledError)):raise

    finally:
        if mode=='write':
            with outline.lock(e):
                try:
                    current=status(e,name)
                    if current['total'] and current['latest']==current['total']:manuscripts.save(e,name)
                except Exception as ex:
                    current=outline.read(path/'writing-job.json',{})
                    if current.get('token')==token:
                        current['error']='正文已保留，但自动保存稿件失败：'+safe_error(ex)
                        e.write_json(path/'writing-job.json',current)

def display_document(e,name,rows=None,only_unit=None):
    ctx=manuscripts.context(e,name);language=lang.normalize(ctx.get('config',{}).get('language')) if ctx.get('config',{}).get('promptVersion') else 'zh'
    rows=rows if rows is not None else ctx['rows'];path=outline.work(e,name)
    units=tree_units(rows);saved={u['id']:saved_unit(path,u) for u in units};numbers={};by_node={s['node_id']:s for value in saved.values() for s in value.get('sections',[])}
    for row in rows:
        for block in by_node.get(row['id'],{}).get('blocks',[]):
            review_content.objects.register(numbers,block,row['id'])
    result={}
    for unit in units:
        if only_unit and unit['id']!=only_unit:continue
        value=saved[unit['id']]
        if not value:continue
        pool=review_bundle.make({'topic':'','config':{'language':'','requirements':''}},unit,value.get('evidence',{}))
        for section in review_content.render_sections(value['sections'],pool['resources'],storage.project_dir(e.ROOT,e.PROJECT),numbers,pool['evidencePool'],language=language):result[section['node_id']]=section
    return result

def assemble(e,name,include_blocks=False):
    path=outline.work(e,name);state=status(e,name);body={};evidence={};refs={};warnings=[]
    full_units={u['id']:u for u in tree_units(state['rows'])};display=display_document(e,name,state['rows'])
    for unit in state['units']:
        saved=saved_unit(path,full_units[unit['id']])
        if not unit['latest']:warnings.append(unit['serial'])
        if saved:
            body.update({s['node_id']:display[s['node_id']]['markdown'] for s in saved['sections']})
            original=saved.get('evidence',{})
            evidence.update(original)
            if saved.get('sections') and all(s.get('citationPoolVersion') in review_bundle.READ_VERSIONS for s in saved['sections']):
                pool=review_bundle.records(full_units[unit['id']],original)
                for leaf in full_units[unit['id']]['leaves']:evidence[leaf['id']]={**original.get(leaf['id'],{}),'chunks':pool}
    title=manuscripts.context(e,name).get('topic') or name;lines=['# '+title,'']
    if warnings:lines+=['> 草稿：以下写作单元尚未生成或待更新：'+', '.join(warnings),'']
    for row in state['rows']:
        lines+=['#'*min(len(row['serial'].split('.')),6)+' '+row['serial']+' '+row['title'],'',body.get(row['id'],''),'']
        refs.update({pmid:{} for pmid in citations(body.get(row['id'],''))})
    if refs:
        lines+=['## 参考文献','']
        for pmid in sorted(refs,key=int):lines.append(f'- PMID: {pmid}. https://pubmed.ncbi.nlm.nih.gov/{pmid}/')
    result=('\n'.join(lines),state,body,evidence,refs)
    return (*result,{sid:s['displayBlocks'] for sid,s in display.items()}) if include_blocks else result

def export(e,name,fmt):
    return manuscripts.export(e,name,fmt)
