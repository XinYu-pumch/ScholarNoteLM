"""App-wide recall policy and credential-bound embedding verification."""
import json,time
from types import SimpleNamespace
import vector_chunks as chunks

def read(root):
    import embedding_profiles
    return {'method':'api','embeddingProfile':embedding_profiles.store(SimpleNamespace(ROOT=root))['activeProfile']}
def effective(cfg,topk):return topk
def fingerprint(cfg):
    import vector_service as v
    return chunks.digest([v.endpoint(cfg),cfg['model'],cfg.get('modelRevision',''),cfg.get('apiKey','')])
def verified(root,cfg=None):
    import vector_service as v
    cfg=cfg or v.config(SimpleNamespace(ROOT=root));p=root/'config/embedding-verification.json'
    if not cfg['baseUrl'] or not p.exists():return False
    data=json.loads(p.read_text());key=fingerprint(cfg)
    return data.get('fingerprint')==key or key in data.get('verifications',{})
def mark_verified(e,cfg,dimension):
    import storage
    with storage.file_lock(e.ROOT/'config/embedding-verification.lock'):
        path=e.ROOT/'config/embedding-verification.json';old=json.loads(path.read_text()) if path.exists() else {};entries=old.get('verifications',{})
        if old.get('fingerprint'):entries[old['fingerprint']]={k:v for k,v in old.items() if k!='verifications'}
        current={'fingerprint':fingerprint(cfg),'dimension':dimension,'verifiedAt':time.time()};entries[current['fingerprint']]=current
        e.write_json(path,{**current,'verifications':entries})
def snapshot(root):
    import vector_service as v
    cfg=read(root)
    if cfg['method']=='api':cfg['embeddingFingerprint']=fingerprint(v.config(SimpleNamespace(ROOT=root)))
    return cfg
def public(e):
    import vector_service as v
    cfg=read(e.ROOT);emb=v.config(e)
    return {'config':cfg,'apiVerified':verified(e.ROOT,emb),
            'apiModel':((emb.get('name','')+'/') if emb.get('name') else '')+emb['model'] if emb['baseUrl'] else '',
            'apiConfigured':bool(emb['baseUrl'] and emb['model'])}
def rpc(e,op,a):
    if op=='settings':return public(e)
    raise ValueError('请在 Embedding 模型设置中管理检索服务')
