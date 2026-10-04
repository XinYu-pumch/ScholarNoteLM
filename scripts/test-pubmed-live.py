"""Small live E-utilities check, without changing user projects or model credentials."""
import json,os,pathlib,shutil,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
TEST=pathlib.Path(tempfile.mkdtemp(prefix='pubmed-live-',dir=ROOT/'tmp'))
ENV=dict(os.environ,SCHOLARNOTELM_ROOT=str(TEST))
checks=[]
def rpc(action,**args):
 r=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps(dict(action=action,args=args)),text=True,capture_output=True,env=ENV,check=True)
 v=json.loads(r.stdout)
 if not v['ok']:raise RuntimeError(v['error'])
 return v['data']
try:
 p='live-check';w=rpc('query.create',project=p);q=w['queries'][0];f=q['filters'];f['limit']=3
 w=rpc('query.save',project=p,id=q['id'],revision=q['revision'],filters=f,name='Live PubMed verification',text='microglia[tiab] AND 2025[pdat]');q=w['queries'][0]
 w=rpc('query.run',project=p,id=q['id']);q=w['queries'][0]
 assert q['run']['fetched']==3 and q['run']['count']>=3
 assert all(x['pmid'].isdigit() and x['title'] for x in w['corpus']['papers'])
 snap=w['corpus']['snapshot'];first_title=w['corpus']['papers'][0]['title'];count=q['run']['count']
 checks.append('Live ESearch + EFetch, 3 records, complete PMID/title/XML metadata')
 w=rpc('query.save',project=p,id=q['id'],revision=q['revision'],name=q['name'],text='microglia[not_a_real_field]')
 try:rpc('query.run',project=p,id=q['id'])
 except RuntimeError:pass
 else:raise AssertionError('invalid field should be rejected')
 w=rpc('workspace',project=p);assert w['corpus']['snapshot']==snap and w['corpus']['included']==3
 checks.append('Invalid PubMed field fails without replacing the successful run')
 q=w['queries'][0];rpc('query.save',project=p,id=q['id'],revision=q['revision'],name=q['name'],text='zzscholarnotelmzeroresultfixturezz[tiab]')
 w=rpc('query.run',project=p,id=q['id']);assert w['corpus']['included']==0;assert w['queries'][0]['run']['fetched']==0
 assert (TEST/f'data/projects/{p}/search/snapshots/{snap}/pubmed.xml').exists()
 checks.append('Successful zero-hit search replaces current collection; old snapshot retained')
 f['mode']='full'
 q=rpc('workspace',project=p)['queries'][0]
 rpc('query.save',project=p,id=q['id'],revision=q['revision'],name=q['name'],text='38637051[uid]',filters=f)
 w=rpc('query.run',project=p,id=q['id']);assert w['corpus']['included']==1;assert not w['queries'][0]['run']['truncated']
 checks.append('Full retrieval mode with an exact PMID completes without truncation')
 result=dict(passed=True,checks=checks,matched=count,sampleTitle=first_title)
 (ROOT/'docs/PUBMED_LIVE_TEST_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
finally:shutil.rmtree(TEST)
