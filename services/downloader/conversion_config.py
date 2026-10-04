"""Marker identity and compatibility with existing conversion provenance."""
MARKER_KEYS={'device','badrCleanup','cleaningMode','removeLines','pdftextWorkers'}
def identity(root,cfg):return {'engine':'marker','version':'1.6.0','ocr':False}
def matches(root,meta,cfg):
    if meta.get('conversionIdentity'):return meta['conversionIdentity']==identity(root,cfg)
    return meta.get('engine','Marker').startswith('Marker')
