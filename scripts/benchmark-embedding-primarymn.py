"""Explicitly authorized live calibration; secrets remain in existing config only."""
import sys,time,json,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/downloader'))
import engine as e,vector_service as v,vector_chunks as c,embedding_limits as limits
if __name__=='__main__':
 e.PROJECT='4481949eab1f40189ddd7f059a691035';cfg={**v.config(e),'rpm':1800,'tpm':450000,'batchSize':32}
 docs=c.documents(e,v.profile(cfg))
 with c.connect(e) as db:texts=[r['text'] for d in docs for r in c.records_for(db,d['version'],d['metadata'])]
 # Fixed seed-like stratified sample keeps corpus order from biasing toward title fragments.
 sample=[texts[(i*997)%len(texts)] for i in range(96)]
 original=limits.post;records=[]
 limits.estimate=lambda ts:8192*len(ts)
 def post(url,headers,payload,timeout,check):
  start=time.time();r=original(url,headers,payload,timeout,check)
  try:usage=r.json().get('usage',{})
  except Exception:usage={}
  record={'at':start,'seconds':round(time.time()-start,3),'count':len(payload['input']),'chars':sum(map(len,payload['input'])),'status':r.status_code,'usage':usage}
  records.append(record);print(json.dumps(record),flush=True)
  Path('docs/embedding-throughput-20260929/calibration.json').write_text(json.dumps(records,indent=2))
  return r
 limits.post=post
 for repeat in range(2):
  for size in (8,16,32):
   result=v.embed(sample[repeat*32:repeat*32+size],cfg,attempts=1)
   assert len(result)==size
 print('CALIBRATION_COMPLETE',flush=True)
