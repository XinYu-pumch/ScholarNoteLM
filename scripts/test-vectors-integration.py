"""Real index worker subprocess and SQLite vector cache; deterministic localhost embedding fixture only."""
import hashlib,json,os,sys,tempfile,threading,time,subprocess
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import test_paths
from xml.sax.saxutils import escape
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e,vector_service as v,vector_chunks as c,corpus_files as f
requests=[];fail_token='';dimension=4;release_slow=threading.Event();release_slow.set()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  a=json.loads(self.rfile.read(int(self.headers['Content-Length'])));texts=a['input'];requests.extend(texts)
  if fail_token and any(fail_token in t for t in texts):self.send_response(400);self.end_headers();return
  if any('SLOWTAIL' in t for t in texts):release_slow.wait(15)
  values=[]
  for i,t in enumerate(texts):
   raw=hashlib.sha256(t.encode()).digest();vec=[1+raw[j]/255 for j in range(dimension)]
   values.append({'index':i,'embedding':vec})
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'data':values[::-1],'usage':{'prompt_tokens':sum(max(1,len(t)//4) for t in texts)}}).encode())
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='vector-integration-',dir=ROOT/'tmp') as temp:
 e.ROOT=Path(temp);e.PROJECT='test';(e.ROOT/'tmp').mkdir()
 for name in ('services','runtimes'):test_paths.link_directory(e.ROOT/name,ROOT/name)
 def xml(values):
  text='<PubmedArticleSet>'+''.join('<PubmedArticle><MedlineCitation><PMID>'+p+'</PMID><Article><ArticleTitle>Study '+p+'</ArticleTitle><Abstract><AbstractText>'+escape(body)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for p,body in values.items())+'</PubmedArticleSet>'
  e.atomic(f.base(e)/'pubmed/current.xml',text)
 def index(adaptive=False):
  v.start(e,{} if adaptive is None else {"adaptive":adaptive})
  deadline=time.monotonic()+45
  while time.monotonic()<deadline:
   job=v.read_job(e)
   if job['state'] not in v.ACTIVE:return job
   time.sleep(.15)
  raise AssertionError('worker timeout')
 def search(query,method):
  # Run the production RPC in its own process and runtime, as the app does.
  result=subprocess.run([str(test_paths.python(ROOT,'marker')),str(ROOT/'services/downloader/engine.py')],input=json.dumps({'action':'vector.search','args':{'project':'test','query':query,'method':method}}),text=True,capture_output=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(e.ROOT)})
  data=json.loads(result.stdout);assert data['ok'],data
  return data['data']['results']
 cfg={'baseUrl':f'http://127.0.0.1:{server.server_port}/v1','apiKey':'isolated-secret-do-not-export','model':'fixture','autoIndex':False,'adaptive':True,'batchSize':1,'concurrency':2}
 v.rpc(e,'settings.save',cfg)
 first='Immune microbiome evidence. '*30;second='Neuronal pathway evidence. '*30
 xml({'123':first,'456':second});job=index(adaptive=None);assert job['completed']==2 and job['adaptive'] and job['tokenBudget']=='auto',job
 n=len(requests);job=index();assert job['skipped']==2 and len(requests)==n,job
 hits=search('immune','semantic');assert hits and all(h['metadata']['pmid'] in ('123','456') for h in hits)
 xml({'123':'Updated cytokine evidence. '*30});c.sync(e)
 with c.connect(e) as db:
  assert db.execute("SELECT COUNT(*) FROM embedding_owners WHERE pmid='456'").fetchone()[0]==0
  assert db.execute("SELECT COUNT(*) FROM indexed WHERE pmid='456'").fetchone()[0]==0

 assert not search('immune','semantic')
 job=index();assert job['completed']==1,job
 hits=search('cytokine','semantic');assert len(hits)==1 and hits[0]['metadata']['pmid']=='123',hits
 xml({'123':first,'456':second});job=index();assert job['completed']==2 and job['skipped']==0 and job['items'][0]['newEmbeddings']==0 and job['items'][1]['newEmbeddings']==1,job
 assert not (f.base(e)/'vectors/chunks/456.jsonl').exists()
 exported=v.rpc(e,'export',{'pmid':'456'});assert Path(exported['path']).exists()
 assert json.loads(Path(exported['path']).read_text().splitlines()[0])['metadata']['pmid']=='456'
 # One batch fails while another succeeds: retry must reuse the successful batch.
 fail_token='FAILMARK';xml({'123':('Healthy new batch. '*25)+'\n\n'+('FAILMARK other batch. '*25)})
 job=index();assert job['failed']==1 and not c.documents(e,v.profile(v.config(e)))[0]['indexed'],job
 healthy_calls=sum('Healthy new batch.' in x for x in requests);fail_token='';job=index()
 assert job['completed']==1 and sum('Healthy new batch.' in x for x in requests)==healthy_calls,job
 # Same-named model changing dimensions must not publish an incompatible index.
 dimension=5;xml({'123':'Brand new content. '*30});job=index();assert job['failed']==1 and '维度' in job['items'][0]['error'],job
 # A short document must publish while a later embedding response is still blocked.
 dimension=4;release_slow.clear()
 v.rpc(e,'settings.save',{'rpm':1800,'tpm':450000})
 xml({'10':'Early document evidence. '*20,'20':'\n\n'.join((('EARLY' if n<31 else 'SLOWTAIL')+f' paragraph {n}. ')*20 for n in range(60))})
 v.start(e,{'adaptive':True});deadline=time.monotonic()+12;saw_overlap=False
 try:
  while time.monotonic()<deadline:
   job=v.rpc(e,'progress',{})['job']
   if job['completed']>=1 and job['vectorProgress']['completed']<job['vectorProgress']['total']:
    saw_overlap=True;break
   if job['state'] not in v.ACTIVE:break
   time.sleep(.1)
 finally:release_slow.set()
 assert saw_overlap,job
 deadline=time.monotonic()+20
 while time.monotonic()<deadline:
  job=v.read_job(e)
  if job['state'] not in v.ACTIVE:break
  time.sleep(.1)
 assert job['state']=='done' and job['completed']==2 and not job['failed'],job
 for path in (f.base(e)/'logs').rglob('*.json'):assert 'isolated-secret-do-not-export' not in path.read_text()
 print(json.dumps({'success':True,'checks':['SQLite vector cache recall','real worker subprocess','response index reordering','incremental reuse','removed and stale evidence excluded','removed article index registration and cache ownership cleanup','removed article regenerates embeddings; retained article reuses cache','partial batch retry','dimension mismatch','redacted logs','document published before all embeddings finish','independent live progress'],'embeddingRequests':len(requests)},ensure_ascii=False))
server.shutdown()
