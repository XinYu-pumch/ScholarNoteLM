"""Credential-free project model selection; provider credentials/limits stay live."""
import json
from types import SimpleNamespace
import storage

KEYS=('id','name','baseUrl','model','modelRevision')
def selection(cfg):return {k:cfg.get(k,'') for k in KEYS}
def path(e):
    folder=storage.project_dir(e.ROOT,e.PROJECT)/'metadata';target=folder/'embedding-model.json'
    if folder.is_symlink() or target.is_symlink():raise ValueError('项目模型配置不能使用符号链接')
    return target
def read(e):
    p=path(e)
    return json.loads(p.read_text()) if p.is_file() else None
def resolve(e,selected):
    import embedding_profiles,vector_service as v
    try:live=embedding_profiles.get(e,selected['id'])
    except ValueError:live={**v.DEFAULTS,'apiKey':''}
    return {**live,**selected}
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
