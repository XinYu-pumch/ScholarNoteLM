"""Credential-free provider presets and explicit embedding request protocols."""
from urllib.parse import urlparse
import urllib.request

PRESETS=(
    {'id':'siliconflow','name':'siliconflow','baseUrl':'https://api.siliconflow.cn/v1/embeddings',
     'model':'Pro/BAAI/bge-m3','batchSize':32,'concurrency':4,'rpm':1800,'tpm':450000,'timeout':120,'adaptive':True},
    {'id':'jina','name':'jina','baseUrl':'https://api.jina.ai/v1/embeddings',
     'model':'jina-embeddings-v4','batchSize':32,'concurrency':2,'rpm':100,'tpm':100000,'timeout':120,'adaptive':True},
)

def presets():
    return [{**p,'apiKey':'','modelRevision':'','autoIndex':True} for p in PRESETS]

def is_jina(cfg):
    return urlparse(cfg.get('baseUrl','')).hostname=='api.jina.ai'

def protocol(cfg):
    # Do not change signatures for existing OpenAI-compatible providers.
    return 'jina-dense-retrieval-v1' if is_jina(cfg) else ''

def payload(texts,cfg,purpose):
    if not is_jina(cfg):return {'model':cfg['model'],'input':texts,'encoding_format':'float'}
    model=cfg['model'].removeprefix('jina-ai/')
    result={'model':model,'input':texts,'embedding_type':'float','truncate':False}
    if model.startswith(('jina-embeddings-v3','jina-embeddings-v4','jina-embeddings-v5')):
        result['task']='retrieval.query' if purpose=='query' else 'retrieval.passage'
    return result

def model_ids(data,cfg):
    rows=[p for p in data if isinstance(p,dict) and isinstance(p.get('id'),str) and p['id']]
    if not is_jina(cfg):return sorted({p['id'] for p in rows})
    # Jina /models also includes chat, OCR, rerankers and multi-vector ColBERT.
    return sorted({p['id'].removeprefix('jina-ai/') for p in rows
                   if 'embeddings' in p.get('output_modalities',[]) and 'text' in p.get('input_modalities',[])
                   and not p['id'].removeprefix('jina-ai/').startswith('jina-colbert')})

def system_proxy(url):
    """Honor the user's HTTP(S) proxy, including macOS settings; local APIs stay direct.

    Keep httpx trust_env=False: only proxy routing is imported, not implicit TLS
    or certificate overrides. HTTPS continues to use normal certificate checks.
    """
    parsed=urlparse(url)
    if parsed.hostname in ('localhost','127.0.0.1','::1') or urllib.request.proxy_bypass(parsed.hostname or ''):return None
    proxies=urllib.request.getproxies()
    value=proxies.get(parsed.scheme) or proxies.get('all')
    return value if value and urlparse(value).scheme in ('http','https') else None
