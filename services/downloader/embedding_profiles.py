"""Named embedding configurations."""
import json,os,uuid
import storage

def store(e):
    path=e.ROOT/'config/embedding.json'
    if not path.exists():return {'profiles':[],'activeProfile':''}
    data=json.loads(path.read_text())
    if 'profiles' not in data:raise ValueError('config/embedding.json 是已停用的单配置格式，请移走该文件后在设置中重新配置')
    # The id 'legacy' is just the first profile's name in existing installs; keep it stable.
    for profile in data['profiles']:
        for key,default in (('rpm',60),('tpm',120000)):profile.setdefault(key,default)
    return data

def get(e,pid):
    import vector_service as v
    found=next((p for p in store(e)['profiles'] if p['id']==pid),None)
    if not found:raise ValueError('Embedding 配置不存在，请重新选择')
    return {**v.DEFAULTS,**found}

def active(e):
    import vector_service as v
    data=store(e)
    return get(e,data['activeProfile']) if data['activeProfile'] else {**v.DEFAULTS,'id':'','name':''}

def form(e,args):
    import vector_service as v
    if 'id' not in args:return active(e)
    return get(e,args['id']) if args['id'] else {**v.DEFAULTS,'id':'','name':''}

def write(e,data):
    path=e.ROOT/'config/embedding.json';e.write_json(path,data)
    if os.name!='nt':path.chmod(0o600)

def save(e,args):
    import vector_service as v
    with storage.file_lock(e.ROOT/'config/embedding-settings.lock'):
        data=store(e);cfg=v.validated(e,args);pid=cfg.get('id') or uuid.uuid4().hex
        name=args.get('name',cfg.get('name') or '默认配置')
        if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValueError('配置名称须为 1–80 个字符')
        name=name.strip()
        if any(p['id']!=pid and p['name'].casefold()==name.casefold() for p in data['profiles']):raise ValueError('配置名称已存在，请使用不同名称')
        cfg.update(id=pid,name=name)
        data['profiles']=[cfg if p['id']==pid else p for p in data['profiles']]
        if not any(p['id']==pid for p in data['profiles']):data['profiles'].append(cfg)
        if not data['activeProfile'] or args.get('activate') is True:data['activeProfile']=pid
        import project_embedding
        project_embedding.pin_existing(e)
        write(e,data);return pid

def activate(e,pid):
    with storage.file_lock(e.ROOT/'config/embedding-settings.lock'):
        import project_embedding
        project_embedding.pin_existing(e)
        get(e,pid);data=store(e);data['activeProfile']=pid;write(e,data)

def delete(e,pid):
    with storage.file_lock(e.ROOT/'config/embedding-settings.lock'):
        import project_embedding
        project_embedding.pin_existing(e)
        get(e,pid);data=store(e)
        if data['activeProfile']==pid and len(data['profiles'])>1:raise ValueError('请先在 Embedding 设置启用其他配置，再删除当前使用的配置')
        data['profiles']=[p for p in data['profiles'] if p['id']!=pid]
        if data['activeProfile']==pid:data['activeProfile']=''
        write(e,data)

def models(e,args):
    import httpx,vector_service as v
    from embedding_providers import system_proxy,model_ids
    cfg=v.validated(e,{**args,'model':args.get('model') or 'model-list'});base=cfg['baseUrl'].rstrip('/')
    if not base:raise ValueError('请先填写 API 地址')
    for suffix in ('/embeddings','/models'):
        if base.endswith(suffix):base=base[:-len(suffix)];break
    from urllib.parse import urlparse
    if not urlparse(base).path.strip('/'):base+='/v1'
    headers={'Authorization':'Bearer '+cfg['apiKey']} if cfg.get('apiKey') else {}
    try:
        r=httpx.get(base+'/models',headers=headers,timeout=25,follow_redirects=False,trust_env=False,proxy=system_proxy(base+'/models'))
        if r.status_code!=200:raise ValueError(f'获取模型列表失败（HTTP {r.status_code}）')
        try:payload=r.json()
        except ValueError:raise ValueError('服务返回的模型列表不是有效 JSON') from None
        if not isinstance(payload,dict):raise ValueError('服务返回的模型列表格式无效')
        data=payload.get('data',[])
        if not isinstance(data,list):raise ValueError('服务返回的模型列表格式无效')
        return model_ids(data,cfg)
    except httpx.HTTPError:raise ValueError('模型列表连接失败，请检查地址与网络') from None
