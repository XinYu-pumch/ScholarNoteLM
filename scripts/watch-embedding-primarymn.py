import json,sys,time,os
from pathlib import Path
base=Path('workspace/PrimaryMN');seen=None
while True:
 j=json.loads((base/'metadata/vector-job.json').read_text());pid=j.get('pid')
 try:os.kill(pid,0);live=True
 except (OSError,TypeError):live=False
 print(json.dumps({'state':j['state'],'pid':pid,'live':live,'completed':j['completed'],'failed':j['failed'],'adaptive':j.get('adaptiveProgress'),'error':j.get('error')}),flush=True)
 if j['state'] not in ('queued','running','stopping') or not live:break
 time.sleep(15)
