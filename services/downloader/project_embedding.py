"""Credential-free project model selection; provider credentials/limits stay live."""
import json
from types import SimpleNamespace
import storage

KEYS=('id','name','baseUrl','model','modelRevision')
def selection(cfg):return {**{k:cfg.get(k,'') for k in KEYS},'requiresKey':bool(cfg.get('requiresKey') or cfg.get('apiKey'))}
def path(e):
    folder=storage.project_dir(e.ROOT,e.PROJECT)/'metadata';target=folder/'embedding-model.json'
    if folder.is_symlink() or target.is_symlink():raise ValueError('项目模型配置不能使用符号链接')
    return target
def read(e):
    p=path(e)
    return json.loads(p.read_text()) if p.is_file() else None
def resolve(e,selected):
    import embedding_profiles,vector_service as v
    profiles=[{**v.DEFAULTS,**p} for p in embedding_profiles.store(e)['profiles']]
    # An explicitly bound provider keeps live limits/credentials even when its
    # selected model changes, but never send its key to a different endpoint.
    live=next((p for p in profiles if p['id']==selected.get('id') and v.endpoint(p)==v.endpoint(selected)),None)
    matches=[p for p in profiles if v.profile(p)==v.profile(selected)] if live is None else []
    if live is None and len(matches)==1:live=matches[0]
    state='ready' if live else 'ambiguous' if len(matches)>1 else 'missing'
    if live and selected.get('requiresKey') and not live.get('apiKey'):state='needs_key'
    return {**v.DEFAULTS,**(live or {'apiKey':''}),**selected,
            '_connectionState':state,'_providerId':live.get('id','') if live else ''}

def connection(cfg):
    state=cfg.get('_connectionState','ready' if cfg.get('baseUrl') and cfg.get('model') else 'unconfigured')
    messages={'missing':'项目材料和索引已保留，请重新配置原 Embedding 服务。',
              'ambiguous':'存在多个匹配的 Embedding 配置，请选择一个用于当前项目。',
              'needs_key':'项目材料和索引已保留，请补充原 Embedding 服务的 API Key。',
              'unconfigured':'请先配置 Embedding 服务；本地文本块仍可浏览。'}
    return {'state':state,'profileId':cfg.get('_providerId',cfg.get('id','')),'message':messages.get(state,'')}

def require_connection(cfg):
    status=connection(cfg)
    if status['state']!='ready':raise ValueError(status['message'])
def config(e):
    import embedding_profiles
    if not getattr(e,'PROJECT',None):return embedding_profiles.active(e)
    selected=read(e)
    return resolve(e,selected) if selected else embedding_profiles.active(e)
def bind(e,cfg,only_if_unbound=False):
    with storage.file_lock(path(e).parent/'embedding-model.lock'):
        current=read(e)
        if only_if_unbound and current:return current
        value=selection(cfg);e.write_json(path(e),value);return value
def pin_existing(e):
    """Before changing the global default, preserve existing projects' selection."""
    import embedding_profiles
    cfg=embedding_profiles.active(e)
    if not cfg.get('id'):return
    for project in storage.config(e.ROOT).get('projects',{}):
        context=SimpleNamespace(ROOT=e.ROOT,PROJECT=project,write_json=e.write_json)
        bind(context,cfg,only_if_unbound=True)
