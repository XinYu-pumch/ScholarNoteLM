"""One real PMC S3 download in an isolated project tree; no user corpus changes."""
import json,os,pathlib,subprocess,time,sys
root=pathlib.Path(__file__).resolve().parents[1];test=root/'tmp/pdf-live-verification';test.mkdir(exist_ok=True)
for name in ['runtimes','services']:
    if not (test/name).exists():(test/name).symlink_to(root/name,target_is_directory=True)
(test/'data/reference/jcr').mkdir(parents=True,exist_ok=True)
import shutil
shutil.copy(root/'services/reference/jcr/default-2025.xlsx',test/'data/reference/jcr/default-2025.xlsx')
env={**os.environ,'SCHOLARNOTELM_ROOT':str(test),'PYTHONDONTWRITEBYTECODE':'1'}
def rpc(action,args={}):
    r=subprocess.run([str(root/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':args}),text=True,capture_output=True,env=env)
    v=json.loads(r.stdout)
    if not v['ok']:raise RuntimeError(v['error'])
    return v['data']
rpc('download.settings.save',{'mirrors':[],'email':'','enhanced':False,'timeout':20,'attempts':3})
xml='''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>27019327</PMID><Article><ArticleTitle>Commensal microbiota affects ischemic stroke outcome by regulating intestinal γδT cells</ArticleTitle><Abstract><AbstractText>Live download verification.</AbstractText></Abstract><Journal><Title>Nature Medicine</Title><JournalIssue><PubDate><Year>2016</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pubmed">27019327</ArticleId><ArticleId IdType="pmc">PMC4860105</ArticleId><ArticleId IdType="doi">10.1038/nm.4068</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''
rpc('xml.import',{'project':'pdf-verification','name':'PMC4860105.xml','xml':xml})
state=rpc('download.list',{'project':'pdf-verification'})
for b in state['batches']:
    if b['state'] in ['running','queued','paused']:rpc('download.control',{'project':'pdf-verification','id':b['id'],'command':'cancel'})
batch=rpc('download.start',{'project':'pdf-verification'});print('Batch',batch,flush=True)
for n in range(100):
    time.sleep(2);state=rpc('download.list',{'project':'pdf-verification'});b=next(b for b in state['batches'] if b['id']==batch['id'])
    if n%5==0:print(b['state'],b['counts'],[(i['stage'],i['error']) for i in b['items']],flush=True)
    if b['state'] in ['done','paused','cancelled']:break
asset=state['assets'].get('27019327');result={'passed':bool(asset and asset['exists']),'batch':b,'asset':asset}
(root/'docs/DOWNLOAD_LIVE_TEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
if not result['passed']:raise RuntimeError('Live PDF failed: '+json.dumps(b))
assert asset['key']=='PMC4860105.1/PMC4860105.1.pdf'
assert asset['md5']=='8a84a83ba61a0aa6ae43ca0d1a20ea69'
assert asset['path'].endswith('/27019327.pdf')
report=rpc('download.report',{'project':'pdf-verification','id':batch['id']})
assert 'Enhanced rescue: False' in report['text']
print('PASS',asset['pages'],'pages',asset['bytes'],'bytes',asset['path'],flush=True)
