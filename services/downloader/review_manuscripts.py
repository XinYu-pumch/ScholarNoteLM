"""Immutable manuscripts with shared image storage and one mutable writing round.

Call mutations under review_service.lock. Reset uses a strict allowlist and
never traverses exports or manuscripts. Frozen display blocks include images.
"""
import content_language as lang
import base64,hashlib,json,os,re,shutil,time,uuid
import review_service as outline
import manuscript_storage

RESET_DIRS=('review_parts','sections','prompts','retrieval','logs')
RESET_FILES=('writing-job.json','writing-round.json')

def fingerprint(rows):
    return hashlib.sha256(json.dumps([(r['serial'],r['title']) for r in rows],ensure_ascii=False).encode()).hexdigest()

def context(e,name):
    import review_writing as w
    path=outline.work(e,name);pinned=outline.read(outline.safe(path,'writing-round.json'))
    if pinned and pinned.get('materialSnapshot'):return pinned
    # Upgrade old workspaces from the input actually used to write their body.
    candidates=[]
    for section in outline.safe(path,'sections').glob('*.json'):
        if section.is_symlink():raise ValueError('综述片段不能使用符号链接')
        saved=w.read_artifact(section)
        if re.fullmatch('[a-f0-9]{32}',saved.get('run','')):candidates.append((saved.get('created',0),saved['run']))
    token=outline.read(path/'writing-job.json',{}).get('token','')
    if re.fullmatch('[a-f0-9]{32}',token):candidates.append((-1,token))
    for _,token in sorted(candidates,reverse=True):
        value=w.read_artifact(outline.safe(path,'logs',token,'input.json'))
        if value.get('rows') and (not pinned or fingerprint(value['rows'])==pinned['outlineHash']):
            ctx=pinned or {'id':token,'rows':value['rows'],'outlineHash':fingerprint(value['rows']),'topic':value.get('topic',''),'config':value.get('config',{})}
            if value.get('modelsSignature'):
                frozen={k:value[k] for k in ('sourceSignature','modelsSignature','retrieval') if k in value}
                cfg=frozen.get('retrieval',{})
                # Recover historical identity only when it reproduces the original signature.
                if cfg.get('embeddingProfile') and not cfg.get('embeddingModel'):
                    import embedding_profiles,project_embedding
                    try:
                        candidate={**cfg,'embeddingModel':project_embedding.selection(embedding_profiles.get(e,cfg['embeddingProfile']))}
                        if frozen['modelsSignature'] in w.retrieval.compatible_signatures(e.ROOT,candidate):frozen['retrieval']=candidate
                    except ValueError:pass
                ctx={**ctx,'materialSnapshot':frozen}
            return ctx
    if pinned:return pinned
    rows=w.rows_at(e,path);state=outline.vstate(e,name,'current')
    return {'id':'legacy','rows':rows,'outlineHash':fingerprint(rows),'topic':state.get('topic',''),'config':w.config(path)}

def freeze(e,name):
    value=context(e,name);e.write_json(outline.work(e,name)/'writing-round.json',value);return value

def new_round(e,name,rows,topic,cfg):
    value={'id':uuid.uuid4().hex,'created':time.time(),'rows':rows,'outlineHash':fingerprint(rows),'topic':topic,'config':cfg}
    e.write_json(outline.work(e,name)/'writing-round.json',value);return value

def payload_hash(value):
    return hashlib.sha256(json.dumps({k:v for k,v in value.items() if k not in ('id','created','label')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def folder(e,name):return outline.safe(outline.work(e,name),'manuscripts')
def get(e,name,ident):
    if not re.fullmatch(r'[a-f0-9]{64}',ident or ''):raise ValueError('稿件标识无效')
    result=outline.read(outline.safe(folder(e,name),ident,'document.json'))
    if not result:raise ValueError('已保存稿件不存在')
    result=manuscript_storage.unpack(folder(e,name),result)
    if result.get('id')!=ident or payload_hash(result)!=ident:raise ValueError('已保存稿件校验失败，原始正文未清理')
    return result

def store(e,name,value):
    """Publish only after a lossless round trip; caller holds the review lock."""
    ident=value['id']
    if payload_hash(value)!=ident:raise ValueError('已保存稿件校验失败，原稿未修改')
    target=outline.safe(folder(e,name),ident,'document.json')
    compact=manuscript_storage.pack(folder(e,name),value,e.atomic)
    if manuscript_storage.unpack(folder(e,name),compact)!=value:
        raise ValueError('稿件压缩校验失败，原稿未修改')
    e.write_json(target,compact)

def listing(e,name,drafts=False):
    result=[]
    for d in folder(e,name).glob('*/summary.json'):
        if d.is_symlink() or d.parent.is_symlink():raise ValueError('稿件路径不能使用符号链接')
        value=outline.read(d)
        if bool(value.get('partial'))!=drafts:continue
        result.append({k:value[k] for k in ('id','created','label','topic','partial','outlineHash')})
    return sorted(result,key=lambda v:v['created'],reverse=True)

def capture(e,name):
    import review_writing as w,review_export,review_bundle
    path=outline.work(e,name);ctx=context(e,name);rows=ctx['rows'];units=w.tree_units(rows)
    saved={u['id']:w.saved_unit(path,u) for u in units}
    if not any(s.get('sections') for s in saved.values()):return None
    display=w.display_document(e,name,rows);sections={};blocks={};refs={};pmids=set()
    for row in rows:
        node=display.get(row['id'],{});sections[row['serial']]=node.get('markdown','');blocks[row['serial']]=node.get('displayBlocks',[])
        pmids.update(w.citations(node.get('markdown','')))
    for u in units:
        value=saved[u['id']];evidence=value.get('evidence',{})
        shared=bool(value.get('sections')) and all(s.get('citationPoolVersion') in review_bundle.READ_VERSIONS for s in value['sections'])
        records=review_bundle.records(u,evidence) if shared else None
        for node in u['nodes']:
            seen=set();entries={}
            for chunk in (records if records is not None and node in u['leaves'] else evidence.get(node['id'],{}).get('chunks',[])):
                entries.setdefault(chunk['metadata']['pmid'],[]).append(review_export.reference_entry(chunk,w.storage.project_dir(e.ROOT,e.PROJECT),seen))
            refs[node['serial']]=entries
    partial=any(not w.complete_unit(u,saved[u['id']]) for u in units)
    # No live asset paths, provider secrets, or model lookups are needed to read/export this.
    return {**({'contentLanguage':lang.normalize(ctx['config'].get('language'))} if ctx.get('config',{}).get('promptVersion') else {}),'topic':ctx['topic'] or name,'rows':[{'serial':r['serial'],'title':r['title']} for r in rows],
            'outlineHash':ctx['outlineHash'],'sections':sections,'blocks':blocks,'references':refs,'pmids':sorted(pmids,key=int),'partial':partial,
            'models':sorted({s.get('model','') for s in saved.values() if s.get('model')})}

def save(e,name,keep_draft=False):
    value=capture(e,name)
    if value is None or (value['partial'] and not keep_draft):return None
    ident=payload_hash(value)
    target=outline.safe(folder(e,name),ident,'document.json')
    if target.exists():
        existing=get(e,name,ident)
        if 'storageFormat' not in outline.read(target):store(e,name,existing)
        e.write_json(target.parent/'summary.json',{k:existing[k] for k in ('id','created','label','topic','partial','outlineHash')})
        return existing
    created=time.time();kind='草稿' if value['partial'] else '完整稿'
    value.update(id=ident,created=created,label=f'{name}_{kind}_{time.strftime("%Y%m%d-%H%M%S",time.localtime(created))}_{ident[:8]}')
    store(e,name,value)
    if get(e,name,ident)!=value:raise ValueError('稿件保存校验失败，未清理正文')
    e.write_json(target.parent/'summary.json',{k:value[k] for k in ('id','created','label','topic','partial','outlineHash')})
    return value

def before_outline_change(e,name):
    # Pin IDs and the complete original hierarchy before nodes/CSV are changed.
    path=outline.work(e,name)
    if not (path/'writing-round.json').exists() and not any((path/d).exists() for d in ('sections','prompts','review_parts')):return
    freeze(e,name);save(e,name,keep_draft=True)

def reset(e,name):
    import review_writing as w
    w.ensure_idle(e,name);outline.idle(outline.vstate(e,name,'current'))
    path=outline.work(e,name)
    targets=[outline.safe(path,n) for n in (*RESET_DIRS,*RESET_FILES)]
    for target in targets:
        if target.is_dir() and any(p.is_symlink() for p in target.rglob('*')):raise ValueError('中间产物包含符号链接，未执行重置')
    # Capture AND verify before moving even one current artifact.
    archived=save(e,name,keep_draft=True)
    stage=path/('.reset-'+uuid.uuid4().hex);stage.mkdir();moved=[]
    try:
        for target in targets:
            if target.exists():os.replace(target,stage/target.name);moved.append(target)
    except BaseException:
        for target in reversed(moved):os.replace(stage/target.name,target)
        stage.rmdir();raise
    shutil.rmtree(stage)
    return archived

def preview(value):
    blocks=[{'type':'markdown','text':'# '+value['topic']}]
    if value['partial']:blocks.append({'type':'markdown','text':'> Draft: some sections are incomplete.' if value.get('contentLanguage')=='en' else '> 草稿：部分章节尚未完成。'})
    for row in value['rows']:
        blocks.append({'type':'markdown','text':'#'*min(len(row['serial'].split('.')),6)+' '+row['serial']+' '+row['title']})
        blocks.extend(value['blocks'].get(row['serial'],[]))
    if value['pmids']:blocks.append({'type':'markdown','text':('## References\n\n' if value.get('contentLanguage')=='en' else '## 参考文献\n\n')+'\n'.join('- PMID: '+p for p in value['pmids'])})
    return {'markdown':'','displayBlocks':blocks}

def export(e,name,fmt,ident=None):
    import review_export,review_content
    if fmt not in ('md','html','docx'):raise ValueError('不支持的导出格式')
    value=get(e,name,ident) if ident else capture(e,name)
    if value is None:raise ValueError('当前没有可导出的正文')
    if not ident:
        value.update(id=payload_hash(value),label=name+('_草稿' if value['partial'] else '_完整稿'))
    out=outline.safe(outline.work(e,name),'exports');out.mkdir(exist_ok=True)
    # Each request owns a fresh directory, including its Markdown image resources.
    export_name=value['label']+'_'+uuid.uuid4().hex[:8]
    bundle=out/export_name;bundle.mkdir(exist_ok=False)
    dest=bundle/(export_name+'.'+fmt)
    try:
        if fmt=='md':
            def image_file(block):
                mime,encoded=block['dataUrl'].split(';base64,',1);raw=base64.b64decode(encoded,validate=True)
                if mime not in ('data:image/png','data:image/jpeg','data:image/gif','data:image/webp'):raise ValueError('图片格式无效')
                relative='resources/'+hashlib.sha256(raw).hexdigest()+'.'+mime.split('/')[-1];e.atomic(bundle/relative,raw);return relative
            lines=['# '+value['topic'],'']
            if value['partial']:lines+=['> Draft: some sections are incomplete.' if value.get('contentLanguage')=='en' else '> 草稿：部分章节尚未完成。','']
            for row in value['rows']:lines+=['#'*min(len(row['serial'].split('.')),6)+' '+row['serial']+' '+row['title'],'',review_content.markdown(value['blocks'].get(row['serial'],[]),image_file,language=value.get('contentLanguage','zh')),'']
            if value['pmids']:lines+=['## References' if value.get('contentLanguage')=='en' else '## 参考文献','',*['- PMID: '+p+'. https://pubmed.ncbi.nlm.nih.gov/'+p for p in value['pmids']]]
            e.atomic(dest,'\n'.join(lines))
        elif fmt=='html':e.atomic(dest,review_export.html_document(value['topic'],value['rows'],value['sections'],value['references'],value['partial'],value['blocks'],language=value.get('contentLanguage','zh')))
        else:review_export.word_document(dest,value['topic'],value['rows'],value['sections'],value['partial'],value['blocks'],language=value.get('contentLanguage','zh'))
    except BaseException:
        shutil.rmtree(bundle);raise
    return {'path':str(dest),'partial':value['partial'],'manuscriptId':value['id']}
