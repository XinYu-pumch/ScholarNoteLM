"""Exhaustive current-corpus/cache/Chroma consistency audit; no network requests."""
import sys,json,math,struct,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/downloader'))
import engine as e,vector_service as v,vector_chunks as c
import numpy as np
if __name__=='__main__':
 e.PROJECT='4481949eab1f40189ddd7f059a691035';cfg=v.config(e);profile=v.profile(cfg);c.sync(e);docs=c.documents(e,profile)
 expected={};missing=[];invalid=[];unique=set();empty=[]
 with c.connect(e) as db:
  for d in docs:
   records=c.records_for(db,d['version'],d['metadata'])
   if not records:empty.append({'pmid':d['pmid'],'title':d['title'],'sourceKind':d['sourceKind']});continue
   if not d['indexed'] or not d['metadataReady']:missing.append(d['pmid'])
   signature=c.input_signature(records)
   for r in records:
    h=c.digest(c.embedding_text(r));unique.add(h)
    cached=db.execute('SELECT e.dimension,e.vector FROM embeddings e JOIN embedding_owners o ON e.profile=o.profile AND e.input_hash=o.input_hash WHERE e.profile=? AND e.input_hash=? AND o.pmid=?',(profile,h,d['pmid'])).fetchone()
    if not cached:missing.append(r['id']);continue
    vec=np.frombuffer(cached['vector'],dtype=np.float32)
    if cached['dimension']!=1024 or len(vec)!=1024 or not np.isfinite(vec).all() or not np.any(vec):invalid.append(r['id'])
    expected[r['id']+'-'+h[:20]]=(d['pmid'],r['id'],signature,cached['vector'])
 with v.chroma_lock(e):
  coll=v.collection(e,profile);ids=list(expected);count=coll.count();assert count==len(expected),(count,len(expected))
  for at in range(0,len(ids),256):
   batch=ids[at:at+256];result=coll.get(ids=batch,include=['embeddings','metadatas']);assert set(result['ids'])==set(batch)
   for ident,vec,meta in zip(result['ids'],result['embeddings'],result['metadatas']):
    pmid,chunk,signature,packed=expected[ident]
    assert meta['pmid']==pmid and meta['chunkId']==chunk and meta['documentInputHash']==signature
    assert np.allclose(np.asarray(vec,dtype=np.float32),np.frombuffer(packed,dtype=np.float32),atol=1e-7,rtol=1e-6),ident
 assert not missing and not invalid,{'missing':missing,'invalid':invalid}
 report={'verifiedAt':time.time(),'project':e.PROJECT,'model':cfg['model'],'dimension':1024,'documents':len(docs),'indexedDocuments':sum(bool(d['chunks']) for d in docs),'currentChunks':len(expected),'uniqueInputs':len(unique),'duplicateChunksReusingVectors':len(expected)-len(unique),'chromaVectors':count,'missingVectors':len(missing),'invalidVectors':len(invalid),'documentsWithoutChunks':empty,'allCacheAndChromaVectorsMatch':True}
 Path('docs/embedding-throughput-20260929/completeness-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:val for k,val in report.items() if k!='documentsWithoutChunks'},ensure_ascii=False));print('documentsWithoutChunks',len(empty))
