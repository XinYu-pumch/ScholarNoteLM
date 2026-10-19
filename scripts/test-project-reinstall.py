"""Same-version reinstall: retained workspace, no credentials, real local index worker."""
import hashlib,json,shutil,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import test_paths

ROOT=test_paths.installation_root(__file__)
sys.path[:0]=[str(ROOT/'services/downloader'),str(ROOT/'services/downloader/tests')]
import engine as e,storage,markdown_service as m,artifact_state,vector_service as v,vector_chunks as c,project_embedding as binding,embedding_profiles
from test_scihub_retry import pdf

requests=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(data)
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
  self.wfile.write(json.dumps({'data':[{'index':i,'embedding':[1.,float(len(t)%13+1),2.]} for i,t in enumerate(data['input'])]}).encode())

def install(path):
 (path/'tmp').mkdir(parents=True)
 for name in ('services','runtimes'):test_paths.link_directory(path/name,ROOT/name)
 return path

def index():
 v.start(e,{'adaptive':False});deadline=time.monotonic()+45
 while time.monotonic()<deadline:
  job=v.read_job(e)
  if job['state'] not in v.ACTIVE:
   test_paths.wait_for_worker(job.get('pid'));assert job['state']=='done',job
   return job
  time.sleep(.1)
 raise AssertionError('Index worker timeout')

server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
old=e.ROOT,e.PROJECT
try:
 with tempfile.TemporaryDirectory(prefix='project-reinstall-',dir=ROOT/'tmp') as temp:
  root=Path(temp);workspace=root/'retained';workspace.mkdir()
  e.ROOT=install(root/'installation1');e.PROJECT='reinstall'
  storage.select_workspace(e.ROOT,str(workspace))
  project={'id':e.PROJECT,'name':'Reinstall','description':'Fixture','color':'#123456','papers':[],'messages':[],'sections':[],'tasks':[],'notes':{}}
  storage.register(e.ROOT,{'project':e.PROJECT,'folder':'Reinstall','data':project})
  base=storage.project_dir(e.ROOT,e.PROJECT)
  assert binding.read(e) is None # Project precedes first provider configuration.
  cfg={'id':'','name':'Original','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','apiKey':'fixture-key','autoIndex':False}
  v.rpc(e,'settings.save',cfg)
  body=pdf();text='Mechanism evidence from retained full text. '*30
  e.atomic(base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>Retained study</ArticleTitle><Abstract><AbstractText>Fixture abstract.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
  e.atomic(base/'pdf/1.pdf',body);e.atomic(base/'markdown/1.md',text);e.atomic(base/'markdown/raw/1.md',text)
  conversion={**m.config(e),'device':'mps'}
  e.write_json(e.ROOT/'config/markdown.json',{'device':'mps'})
  e.write_json(base/'metadata/markdown/1.json',{'pdfSha256':hashlib.sha256(body).hexdigest(),'rawSha256':hashlib.sha256(text.encode()).hexdigest(),'cleaningSignature':m.signature(conversion),'conversionConfig':conversion,'rebuildEpoch':artifact_state.epoch(e,'1')})
  assert index()['completed']==1
  assert binding.read(e)['requiresKey'] and 'apiKey' not in binding.read(e)
  pid=v.cache_profile(e,v.config(e));before=c.documents(e,pid)[0]
  e.atomic(base/'review/Retained/review.md','Saved review fixture with a citation (PMID: 1).')
  preserved={p:p.read_bytes() for p in [base/'project.json',base/'metadata/embedding-model.json',base/'metadata/markdown/1.json',base/'markdown/1.md',base/'review/Retained/review.md']}
  with c.connect(e) as db:cached=list(map(tuple,db.execute('SELECT * FROM embeddings')))
  # Delete the installation only. The entire workspace is retained elsewhere.
  shutil.rmtree(e.ROOT);e.ROOT=install(root/'installation2')
  storage.select_workspace(e.ROOT,str(workspace));discovered=storage.initialize(e.ROOT)
  assert discovered['projects']=={'reinstall':'Reinstall'},discovered
  assert m.config(e)['device']=='auto'
  assert m.status(e)['latestCount']==1
  status=v.rpc(e,'status',{});assert status['readyDocuments']==1,status
  assert status['connection']['state']=='missing' and status['storedIndex']['documents']==1,status
  assert c.documents(e,pid)[0]['version']==before['version']
  calls=len(requests)
  for action,args in [('search',{'query':'mechanism'}),('start',{'mode':'recompute','confirm':e.PROJECT})]:
   try:v.rpc(e,action,args)
   except ValueError as error:assert '重新配置' in str(error)
   else:raise AssertionError('Missing service accepted '+action)
  assert v.rpc(e,'search',{'query':'mechanism','method':'keyword'})['results']
  assert len(requests)==calls
  with c.connect(e) as db:assert list(map(tuple,db.execute('SELECT * FROM embeddings')))==cached
  # Recreated config uses a new ID/name/key and the equivalent full endpoint.
  saved=v.rpc(e,'settings.save',{**cfg,'name':'Reconnected','baseUrl':cfg['baseUrl']+'/embeddings','apiKey':'rotated-fixture-key'})
  assert saved['connection']['state']=='ready' and saved['connection']['profileId']==saved['savedProfile']
  assert v.cache_profile(e,v.config(e))==pid
  assert index()['skipped']==1 and len(requests)==calls,'Existing document vectors were recomputed'
  assert v.rpc(e,'search',{'query':'mechanism','method':'semantic'})['results']
  assert len(requests)==calls+1,'Only the new query should be embedded'
  assert all(p.read_bytes()==content for p,content in preserved.items())
  replacement=embedding_profiles.get(e,saved['savedProfile'])
  different={**replacement,'model':'different-fixture'};binding.bind(e,different)
  status=v.rpc(e,'status',{});assert status['readyDocuments']==0 and status['storedIndex']['documents']==1,status
  assert not status['storedIndex']['models'][0]['current']
  binding.bind(e,replacement);assert v.rpc(e,'status',{})['readyDocuments']==1
  assert index()['skipped']==1 and len(requests)==calls+1
  with c.connect(e) as db:assert list(map(tuple,db.execute('SELECT * FROM embeddings')))==cached
  print(json.dumps({'passed':True,'checks':['same-version reinstall and workspace discovery','device-independent Markdown','first index persists model identity','no credentials keeps local index visible','missing service blocks semantic/recompute before writes','offline keyword retrieval','new configuration ID reconnects original model','zero document embedding requests after reinstall','different model isolation and switch-back reuse','saved research files byte-for-byte preserved']},ensure_ascii=False))
finally:
 e.ROOT,e.PROJECT=old;server.shutdown();server.server_close()
