"""Real RPC/worker and local HTTP fixture. Does not use user credentials or literature."""
import json,os,sqlite3,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e,review_service as r,storage
import provider_fixture as pf
requests=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(value);pf.capture(self.headers,value)
  try:
   if value['model']=='slow':time.sleep(4)
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   def send(v):self.wfile.write(('data: '+json.dumps(v,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
   send({'choices':[{'delta':{'reasoning_content':'正在构思'}}]})
   time.sleep(.4)
   text='Serial,Title\n1,引言\n1.1,"背景,机制"\n1.1.1,现有证据的局限\n2,未来方向\n' if value['model']!='invalid' else 'Serial,Title\n1.1,缺失父标题\n'
   for part in (text[:12],text[12:]):send({'choices':[{'delta':{'content':part}}]})
   if value['model']!='truncated':
    send({'choices':[{'delta':{},'finish_reason':'stop'}]});self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with tempfile.TemporaryDirectory(prefix='review-integration-',dir=ROOT/'tmp') as temp:
  app=Path(temp);(app/'runtimes').mkdir();(app/'runtimes/downloader').symlink_to(ROOT/'runtimes/downloader',target_is_directory=True);(app/'services').symlink_to(ROOT/'services',target_is_directory=True);(app/'tmp').mkdir()
  pf.setup(app,ROOT,f'http://127.0.0.1:{server.server_port}/v1',['outline', 'slow', 'invalid', 'truncated'])
  e.ROOT,e.PROJECT=app,'test';base=storage.project_dir(app,'test');e.atomic(base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Fixture study</ArticleTitle><Abstract><AbstractText>All of the fixture abstract.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
  cfg=app/'data/research/research.sqlite3';cfg.parent.mkdir(parents=True)
  def model(name):
   with sqlite3.connect(cfg) as c:
    c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('profiles',json.dumps([pf.profile({'id':'test','model':name,'baseUrl':f'http://127.0.0.1:{server.server_port}/v1','apiKey':'test-secret','temperature':None,'timeout':10})])))
    c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('activeProfile',json.dumps('test')))
  def rpc(op,**a):
   p=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':'review.'+op,'args':{'project':'test','name':'Review1',**a}}),text=True,capture_output=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(app)})
   value=json.loads(p.stdout)
   if not value['ok']:raise RuntimeError(value.get('error'))
   return value['data']
  def wait(version):
   until=time.monotonic()+20
   while time.monotonic()<until:
    d=rpc('get',version=version)
    if d['version']['state'] not in r.ACTIVE:return d
    time.sleep(.12)
   raise AssertionError('generation did not finish')
  model('outline');d=rpc('create',description='isolated fixture');d=rpc('start',version=d['version']['id'],revision=0,topic='免疫综述',requirements='强调证据边界')
  d=wait(d['version']['id']);assert d['version']['state']=='done',d
  assert len(d['rows'])==4 and d['version']['reasoningCharacters']>0
  assert 'All of the fixture abstract.' in requests[0]['messages'][1]['content']
  assert '强调证据边界' in requests[0]['messages'][1]['content'] and '免疫综述' in requests[0]['messages'][1]['content']
  assert 'max_tokens' not in requests[0] and 'temperature' not in requests[0]
  vp=Path(d['path']);assert (vp/'prompt.txt').exists() and r.SYSTEM in (vp/'prompt.txt').read_text()
  assert 'test-secret' not in ''.join(p.read_text() for p in vp.iterdir() if p.is_file())
  original=(vp/'generated.csv').read_text();d=rpc('save',version='v0001',revision=d['version']['revision'],topic='免疫综述',rows=[{'serial':'1','title':'手动修改'},{'serial':'1.1','title':'新分点'}]);assert d['rows'][0]['title']=='手动修改'
  d=rpc('restore',version='v0001',revision=d['version']['revision']);assert (vp/'outline.csv').read_text()==original
  model('slow');vid='current';rpc('start',revision=d['version']['revision'],topic='取消测试');time.sleep(.2);start=time.monotonic();rpc('cancel',version=vid);d=wait(vid)
  assert d['version']['state']=='cancelled' and time.monotonic()-start<2.5,d
  assert (Path(d['path'])/'generated.csv').read_text()==original
  for name,expected in [('invalid','缺少父标题'),('truncated','连接中断')]:
   model(name);rpc('start',revision=d['version']['revision'],topic='错误测试');d=wait('current')
   assert d['version']['state']=='failed' and expected in d['version']['error'],d
   assert (Path(d['path'])/'outline.csv').read_text()==original;assert d['response']
  assert (vp/'generated.csv').read_text()==original
  pf.verify()
  print(json.dumps({'success':True,'requests':len(requests),'checks':['real Rust RPC and independent worker','all abstracts + topic + requirements sent','reasoning activity recognized','complete hierarchy CSV','immutable generated baseline and restore','cancel during first response wait','invalid CSV does not publish','interrupted stream does not publish','prompt.txt export without secrets','current outline retained after cancellation and failed regeneration']},ensure_ascii=False))
finally:server.shutdown();server.server_close()
