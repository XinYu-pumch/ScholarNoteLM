"""Marker identity and compatibility with existing conversion provenance."""
import hashlib,json
MARKER_KEYS={'device','badrCleanup','cleaningMode','removeLines','pdftextWorkers'}
def engine(cfg):return 'marker'
def identity(root,cfg):return {'engine':'marker','version':'1.6.0','ocr':False}
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def matches(root,meta,cfg):
    if meta.get('conversionIdentity'):return meta['conversionIdentity']==identity(root,cfg)
    return meta.get('engine','Marker').startswith('Marker')
