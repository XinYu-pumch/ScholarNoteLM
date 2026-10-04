"""Isolated real download -> Marker handoff. Never changes a user's project."""
import hashlib,json,os,shutil,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEST=Path(tempfile.mkdtemp(prefix='workflow-integration-',dir=ROOT/'tmp'))
for name in ['services','runtimes','models']:(TEST/name).symlink_to(ROOT/name,target_is_directory=True)
ENV={**os.environ,'SCHOLARNOTELM_ROOT':str(TEST),'PYTHONDONTWRITEBYTECODE':'1'}
BIN=ROOT/'cache/tauri-target/debug/research-cli'
def rpc(action,**args):
 r=subprocess.run([str(BIN)],input=json.dumps({'action':action,'args':args}),text=True,capture_output=True,env=ENV,check=True)
 v=json.loads(r.stdout)
 if not v['ok']:raise RuntimeError(v['error'])
 return v['data']
ids=['31777065','32865024','99999999']
xml='<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{i}</PMID><Article><ArticleTitle>Test {i}</ArticleTitle><Abstract><AbstractText>Only an abstract is available for the missing PDF.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for i in ids)+'</PubmedArticleSet>'
rpc('storage.initialize');rpc('xml.import',project='test',name='Workflow test',xml=xml)
base=TEST/'workspace/test'
original={}
for p in ids[:2]:
 source=ROOT/'experiments/marker-workers-20260920/inputs'/f'{p}.pdf'
 original[p]=hashlib.sha256(source.read_bytes()).hexdigest()
 shutil.copy2(source,base/'pdf'/f'{p}.pdf')
settings=rpc('markdown.settings');assert settings['config']['pdftextWorkers']=='auto'
start=rpc('download.start',project='test',convertAfter=True)
print(json.dumps({'fixture':str(TEST),'batch':start},ensure_ascii=False),flush=True)
# No UI or polling RPC until the download worker has autonomously handed off.
deadline=time.monotonic()+90
while not (base/'metadata/markdown-job.json').exists() and time.monotonic()<deadline:time.sleep(.5)
assert (base/'metadata/markdown-job.json').exists(),'Download worker did not hand off autonomously'
job=json.loads((base/'metadata/markdown-job.json').read_text());assert job['requestId']==start['id'];assert len(job['pmids'])==2
print('Autonomous handoff verified; running real Marker on 3- and 46-page PDFs.',flush=True)
deadline=time.monotonic()+1500;last=''
while time.monotonic()<deadline:
 job=json.loads((base/'metadata/markdown-job.json').read_text())
 state=(job['state'],job.get('current'),job['completed'],job['failed'])
 if state!=last:print(state,flush=True);last=state
 if job['state'] not in ('queued','running','stopping'):break
 time.sleep(2)
assert job['state']=='done' and job['completed']==2 and job['failed']==0,job
assert [(i['pages'],i['pdftextWorkers'],i['effectiveTextWorkers']) for i in job['items']]==[(3,1,1),(46,4,4)],job['items']
for p in ids[:2]:
 assert hashlib.sha256((ROOT/'experiments/marker-workers-20260920/inputs'/f'{p}.pdf').read_bytes()).hexdigest()==original[p]
 assert (base/'markdown/raw'/f'{p}.md').is_file() and (base/'markdown'/f'{p}.md').is_file()
assert (base/'abstracts/99999999.md').is_file()
state=rpc('download.list',project='test');assert state['batches'][0]['counts']['failed']==1
assert state['batches'][0]['markdownFollowup']['id']==job['id']
assert rpc('markdown.status',project='test')['markdownCount']==2
rpc('markdown.settings.save',pdftextWorkers=8)
status=rpc('markdown.status',project='test');assert not any(i['needsCleaning'] for i in status['items'])
again=rpc('markdown.start',project='test')
for _ in range(100):
 status=rpc('markdown.status',project='test')
 if status['job']['state'] not in ('queued','running','stopping'):break
 time.sleep(.2)
assert status['job']['skipped']==2 and status['job']['failed']==0,status['job']
assert (Path(status['job']['logPath'])/'marker.log').read_text()==''
result={'passed':True,'fixture':str(TEST),'job':job['id'],'items':job['items'],'checks':['Autonomous download worker handoff without UI polling','Partial download failure still converts available PDFs and preserves abstract','Real Marker auto workers: 3 pages=1, 46 pages=4','Worker settings change reuses existing Markdown without loading models','Repeated status does not create duplicate conversion','Original project PDFs untouched']}
(ROOT/'docs/LITERATURE_WORKFLOW_TEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
