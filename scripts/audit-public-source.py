"""Read-only Git publication audit; report locations, never credential contents."""
import json,re,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
objects=subprocess.check_output(['git','rev-list','--objects','--all'],cwd=root).decode().splitlines()
paths={line.split(' ',1)[0]:line.split(' ',1)[1] for line in objects if ' ' in line}
process=subprocess.Popen(['git','cat-file','--batch'],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
patterns=[re.compile(rb'oc_sk_[A-Za-z0-9_-]{20,}'),re.compile(rb'(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{30,}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
secrets=[];large=[];private=[]
for oid,name in paths.items():
    process.stdin.write((oid+'\n').encode());process.stdin.flush()
    header=process.stdout.readline().split()
    if len(header)!=3:continue
    size=int(header[2]);data=process.stdout.read(size);process.stdout.read(1)
    if header[1]!=b'blob':continue
    if any(p.search(data) for p in patterns):secrets.append({'object':oid,'path':name})
    if size>10*1024*1024:large.append({'object':oid,'path':name,'bytes':size})
    if name.startswith(('config/','workspace/','data/','runtimes/','models/','dist/')):private.append(name)
process.stdin.close();process.wait()
print(json.dumps({'historyObjects':len(paths),'credentialPatternLocations':secrets,'largeHistoricalBlobs':large,'privateHistoricalPaths':sorted(set(private))},ensure_ascii=False,indent=2))
