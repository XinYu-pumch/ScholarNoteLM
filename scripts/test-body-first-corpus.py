"""Read-only regression evaluation; writes only experiments/body-first-v1-implementation."""
import hashlib,json,sys,time
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'services/downloader'),str(ROOT/'experiments/cleaning-ab-20260925')]
import markdown_service as service
from compare import mask,RANGES
from evaluate_ab import BODY,NOISE,line_spans,counts
OUT=ROOT/'experiments/body-first-v1-implementation';OUT.mkdir(exist_ok=True)
manifest=json.loads((ROOT/'experiments/cleaning-ab-20260925/manifest.json').read_text())
regress=json.loads((ROOT/'experiments/cleaning-ab-20260925/evaluation.json').read_text())['onlyARegressions']
rows=[];totals=defaultdict(Counter);rules=Counter();start=time.perf_counter();sources=[]
for item in manifest['documents']:
 p,pid=item['project'],item['pmid'];key=p+'/'+pid;source=ROOT/item['source'];before=source.read_bytes();text=before.decode();published=source.parent.parent/source.name;pub_before=published.read_bytes()
 clean,removed=service.clean(text,{**service.DEFAULTS,'cleaningMode':'body-first-v1'});pred=mask(text,removed)
 row={'project':p,'pmid':pid,'rawSha256':hashlib.sha256(before).hexdigest(),'removed':removed,'metrics':{}}
 for s in removed:
  for rule in s['ruleIds']:rules[rule]+=1
  assert text[s['charStart']:s['charEnd']]==s['text']
 if pid in RANGES[p]:
  c=counts(text,mask(text,line_spans(text,RANGES[p][pid])),pred);row['metrics']['references']=c;totals['references'].update(c)
 if key in BODY:
  c=counts(text,mask(text,line_spans(text,BODY[key])),pred);row['metrics']['body']=c;totals['body'].update(c)
  assert c['removed']==0,(key,'scientific loss',c)
 if key=='HLH/35965424':
  extra=counts(text,mask(text,line_spans(text,[(9,27),(35,47)])),pred)
  assert extra['removed']==0,('unlabelled abstract regression',key,extra)
  row['metrics']['additionalBodyRegression']=extra
 if key in NOISE:
  for category,ranges in NOISE[key].items():
   c=counts(text,mask(text,line_spans(text,ranges)),pred);row['metrics'][category]=c;totals[category].update(c)
 for s in regress:
  if s['document']==key:assert all(pred[s['charStart']:s['charEnd']]),('citation regression',key)
 assert source.read_bytes()==before and published.read_bytes()==pub_before
 sources.append({'path':str(source.relative_to(ROOT)),'rawSha256':hashlib.sha256(before).hexdigest(),'publishedSha256':hashlib.sha256(pub_before).hexdigest()})
 dest=OUT/p;dest.mkdir(exist_ok=True);(dest/(pid+'.md')).write_text(clean);(dest/(pid+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2));rows.append({k:v for k,v in row.items() if k!='removed'})
result={'documents':len(rows),'seconds':time.perf_counter()-start,'totals':totals,'rules':rules,'nineCitationRegressionsFixed':True,'sourcesUnchanged':sources,'reviewScope':'26 bibliography and 8 body/misc targeted assistant-labelled samples, not independent gold','rows':rows}
(OUT/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('rows','sourcesUnchanged')},ensure_ascii=False))
