import json,collections,statistics
from pathlib import Path
base=Path('docs/embedding-throughput-20260929');reports={}
paths={'conservative':Path('workspace/PrimaryMN/logs/vectorization-80a9191edfac422587fd705057ea5a4f/embedding-requests.jsonl'),'resume_verified':Path('workspace/PrimaryMN/logs/vectorization-facbf91181c4479eb82e52fdf008ff94/embedding-requests.jsonl'),'verified_benchmark_initial':base/'verified-benchmark/embedding-requests.jsonl','verified_benchmark_final':base/'verified-benchmark-v2/embedding-requests.jsonl'}
for name,p in paths.items():
 rows=sorted([json.loads(l) for l in p.read_text().splitlines()],key=lambda r:r['at']);left=0;rolling=0;peak_tokens=0;peak_requests=0;points=[]
 for i,r in enumerate(rows):
  rolling+=r['usage'].get('prompt_tokens',0)
  while rows[left]['at']<=r['at']-60:rolling-=rows[left]['usage'].get('prompt_tokens',0);left+=1
  peak_tokens=max(peak_tokens,rolling);peak_requests=max(peak_requests,i-left+1)
  if r['at']>=rows[0]['at']+60:points.append(rolling)
 durations=[r['seconds'] for r in rows];counts=[r['count'] for r in rows]
 result={'requests':len(rows),'inputsIncludingRetries':sum(counts),'actualTokens':sum(r['usage'].get('prompt_tokens',0) for r in rows),'requestSpanSeconds':round(max(r['at']+r['seconds'] for r in rows)-rows[0]['at'],3),'maxRolling60Tokens':peak_tokens,'maxRolling60Requests':peak_requests,'medianRolling60TokensAtRequest':statistics.median(points) if points else None,'withinLimits':peak_tokens<=450000 and peak_requests<=1800,'httpStatusCounts':dict(collections.Counter(r['status'] for r in rows)),'batchRange':[min(counts),max(counts)],'latencyMedian':statistics.median(durations),'latencyP95':sorted(durations)[int(.95*len(durations))]}
 reports[name]=result
print(json.dumps(reports,indent=2));(base/'throughput-audit.json').write_text(json.dumps(reports,indent=2))
assert reports['verified_benchmark_final']['withinLimits']
assert reports['verified_benchmark_final']['inputsIncludingRetries']==8000
