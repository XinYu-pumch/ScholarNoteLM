"""Real Rust RPC + coordinator + download/Marker/index workers, isolated fixtures.
No external network: OA disabled, fixture papers have no DOI/PMCID; embeddings
come from a localhost server. Marker reuses a prepared raw text (no inference).
"""
import hashlib,json,os,subprocess,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import test_paths
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'services/downloader'),str(ROOT/'services/downloader/tests')]
import engine as e,corpus_files as f,markdown_service as m,vector_service as v
from test_scihub_retry import pdf
requests=[];delay=0
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.extend(value['input']);time.sleep(delay)
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
  self.wfile.write(json.dumps({'data':[{'index':i,'embedding':[1.,(len(t)%11)+1.,(len(t)%7)+1.]} for i,t in enumerate(value['input'])]}).encode())
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='library-integration-',dir=ROOT/'tmp') as temp:
 e.ROOT=Path(temp);e.PROJECT='test';(e.ROOT/'tmp').mkdir()
 for name in ('services','runtimes','models'):test_paths.link_directory(e.ROOT/name,ROOT/name)
 env={**os.environ,'SCHOLARNOTELM_ROOT':str(e.ROOT)}
 def rpc(action,**args):
  result=subprocess.run([str(test_paths.cli(ROOT))],input=json.dumps({'action':action,'args':{'project':'test',**args}}),text=True,capture_output=True,env=env,timeout=90)
  value=json.loads(result.stdout);assert value.get('ok'),value
  return value['data']
 def wait(action='library.status',timeout=90):
  deadline=time.monotonic()+timeout
  while time.monotonic()<deadline:
   job=rpc(action)['job']
   if job and job['state'] not in ('queued','running','stopping'):
    test_paths.wait_for_worker(job.get('pid'));return job
   time.sleep(.2)
  raise AssertionError('Timed out: '+str(job))
 base=f.base(e)
 title='Long complete title '+('标题完整 '*45)
 xml='<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>{title if p=="1" else "Abstract only"}</ArticleTitle><Journal><Title>Full journal</Title><JournalIssue><PubDate><Year>2026</Year><Month>Sep</Month></PubDate></JournalIssue></Journal><Abstract><AbstractText>'+('Evidence for the abstract. '*20)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for p in ['1','2'])+'</PubmedArticleSet>'
 e.atomic(base/'pubmed/current.xml',xml);e.atomic(base/'pdf/1.pdf',pdf());f.reconcile(e)
 raw='Original full text evidence. '*40;e.atomic(base/'markdown/raw/1.md',raw)
 e.write_json(base/'metadata/markdown/1.json',{'pdfSha256':e.validate_pdf(base/'pdf/1.pdf')['sha256'],'rawSha256':hashlib.sha256(raw.encode()).hexdigest(),'cleaningSignature':'old'})
 # Only DOI-free Sci-Hub stages run and exit locally; no OA calls.
 with e.db(system=True) as db:db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('config',json.dumps({**e.DEFAULTS,'fastOa':False,'enhanced':False})))
 v.rpc(e,'settings.save',{'baseUrl':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','autoIndex':False})
 print('Starting full pipeline',flush=True);rpc('library.start');j=wait();assert j['state']=='partial' and not j['unindexed'],j
 assert [x['stage'] for x in j['stages']]==['download','markdown','index'],j
 assert (base/'markdown/1.md').exists();assert rpc('vector.status')['readyDocuments']==2
 n=len(requests);rpc('library.start');j=wait();assert j['state']=='done' and len(requests)==n,(j,len(requests),n)
 print('Checking metadata update and cache reuse',flush=True)
 e.atomic(base/'pubmed/current.xml',xml.replace('<Month>Sep</Month>','<Month>Oct</Month>'))
 rpc('vector.start');j=wait('vector.status');assert j['failed']==0 and len(requests)==n,j
 docs=rpc('vector.documents');assert all(d['indexed'] and d['metadataReady'] for d in docs),docs
 metas=[d['metadata'] for d in docs];assert all(x['publicationDate']=='2026 Oct' for x in metas);assert next(x for x in metas if x['pmid']=='1')['title']==title.strip()
 rpc('vector.start',mode='rebuild',confirm='test');j=wait('vector.status');assert j['failed']==0 and len(requests)==n
 rpc('vector.start',mode='recompute',confirm='test');j=wait('vector.status');assert j['failed']==0 and len(requests)>n
 print('Checking single-stage conversion and explicit clear',flush=True)
 n=len(requests);e.atomic(base/'markdown/raw/1.md',raw+'\n\n'+'Another paragraph. '*15)
 rpc('markdown.start');j=wait('markdown.status');assert j['state']=='done' and len(requests)==n and not j.get('vectorFollowup'),j
 csv='\ufeffSerial,Title\r\n1,Imported heading\r\n1.1,Subheading\r\n';d=rpc('review.create',name='Imported',outlineSource='file',fileName='框架.csv',csv=csv)
 assert len(d['rows'])==2 and (base/'review/Imported/imported.csv').read_bytes()==csv.encode()
 rpc('library.clear',scope='index',confirm='test');j=wait();assert j['state']=='done',j
 assert not (base/'vectors').exists();assert rpc('vector.status')['cleared'];assert not (base/'vectors').exists()
 assert (base/'pdf/1.pdf').exists() and (base/'markdown/1.md').exists() and (base/'review/Imported/outline.csv').exists()
 # Clear during an in-flight Embedding request; coordinator must wait for exit.
 delay=2;rpc('vector.start');time.sleep(.3);rpc('library.clear',scope='markdown',confirm='test');j=wait();assert j['state']=='done',j
 assert not (base/'markdown').exists() and not (base/'vectors').exists() and (base/'pdf/1.pdf').exists()
 time.sleep(2);assert not (base/'vectors').exists(),'late worker resurrected deleted vectors'
 print(json.dumps({'success':True,'checks':['real RPC pipeline across all three workers','autoIndex false still indexes pipeline','incremental second run makes zero API calls','metadata update makes zero API calls','complete Unicode title persisted in the index metadata','rebuild cache reuse','explicit recompute','single-stage conversion does not index','file import preserves original','clear blocks polling resurrection','clear waits for in-flight worker'],'embeddingInputs':len(requests)},ensure_ascii=False),flush=True)
server.shutdown()
