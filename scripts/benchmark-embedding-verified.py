"""Live 8000-input throughput trial, no changes to existing project vectors."""
import sys,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/downloader'))
import engine as e,vector_service as v,vector_chunks as c,adaptive_embedding as adaptive
if __name__=='__main__':
 e.PROJECT='4481949eab1f40189ddd7f059a691035';cfg=v.config(e);assert cfg['rpm']==1800 and cfg['tpm']==450000
 job=v.read_job(e);assert job and job['state']=='done' and not job['failed'],job['state']
 docs=c.documents(e,v.profile(cfg));wanted={}
 with c.connect(e) as db:
  for d in docs:
   for r in c.records_for(db,d['version'],d['metadata']):wanted[c.digest(r['text'])]=r['text']
 pending=sorted(wanted.items())[:8000];seen=set();out=Path(sys.argv[1] if len(sys.argv)>1 else 'docs/embedding-throughput-20260929/verified-benchmark');out.mkdir(exist_ok=True)
 assert not (out/'embedding-requests.jsonl').exists(),'Do not append a second trial to the same report'
 last=[0];began=time.time()
 def notify(value):
  (out/'progress.json').write_text(json.dumps(value,indent=2))
  if time.time()-last[0]>15:print(json.dumps(value),flush=True);last[0]=time.time()
 def save(group,values):
  assert len(group)==len(values)
  for (h,_),vec in zip(group,values):
   assert len(vec)==1024 and h not in seen;seen.add(h)
 adaptive.run_inputs(e,cfg,pending,lambda:None,notify,out,save,'verified')
 report={'inputs':len(pending),'validated':len(seen),'seconds':time.time()-began,'model':cfg['model'],'rpmLimit':1800,'tpmLimit':450000}
 assert seen=={h for h,_ in pending};(out/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
