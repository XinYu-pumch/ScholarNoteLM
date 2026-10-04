"""Actual app Rust RPC -> Python worker -> bundled Chromium -> guarded publication.
All papers, settings, files and HTTP traffic are isolated local fixtures.
"""
import base64,hashlib,io,json,os,signal,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e,corpus_files as files
sys.path.insert(0,str(ROOT/'services/downloader/tests'))
from pdf_fixture import pdf
PDF=pdf('10.1234/1')
slow=set();entered={};release={};calls=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  route=urlsplit(self.path).path;calls.append(route)
  if route=='/captcha/challenge/1':
   body=json.dumps({'algorithm':'SHA-256','salt':'private-fixture','signature':'private-signature','maxNumber':50,'challenge':hashlib.sha256(b'private-fixture23').hexdigest()}).encode()
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  if route.startswith('/file/'):
   p=route.rsplit('/',1)[-1];body=pdf(blank=True) if p=='7' else pdf('10.1234/'+p)
   self.send_response(200);self.send_header('Content-Type','application/pdf');self.send_header('Content-Length',str(len(body)))
   if p=='1':self.send_header('Content-Disposition','attachment; filename="paper.pdf"')
   self.end_headers()
   try:
    self.wfile.write(body[:5]);self.wfile.flush()
    if p in slow:entered[p].set();release[p].wait(15)
    self.wfile.write(body[5:])
   except (BrokenPipeError,ConnectionResetError):pass
  elif route.startswith('/entry/'):
   p=route.rsplit('/',1)[-1]
   body=f'''<html><script>setTimeout(()=>document.body.innerHTML='<div class="download"><a href="/file/{p}">PDF</a></div>',80)</script></html>'''.encode()
   if p=='1' and 'access=ok' not in self.headers.get('Cookie',''):
    body=b'<html><body><altcha-widget challengeurl="/captcha/challenge/1"></altcha-widget>captcha</body></html>'
   self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  else:self.send_response(404);self.end_headers()
 def do_POST(self):
  calls.append(urlsplit(self.path).path)
  payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  solution=json.loads(base64.b64decode(payload['captcha']))
  body=json.dumps({'success':solution['number']==23}).encode()
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Set-Cookie','access=ok; Path=/; HttpOnly');self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='scihub-browser-rpc-',dir=ROOT/'tmp') as tmp:
 e.ROOT=Path(tmp);e.PROJECT='BrowserTest'
 for name in ('services','runtimes'):(e.ROOT/name).symlink_to(ROOT/name,target_is_directory=True)
 env={**os.environ,'SCHOLARNOTELM_ROOT':tmp}
 def rpc(action,**args):
  run=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':{'project':e.PROJECT,**args}}),text=True,capture_output=True,env=env,timeout=15)
  value=json.loads(run.stdout);assert value['ok'],value;return value['data']
 def xml(ids):return '<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>Fixture {p}</ArticleTitle><Abstract><AbstractText>Offline fixture.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/{p}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>' for p in ids)+'</PubmedArticleSet>'
 def wait(bid,state='done'):
  deadline=time.monotonic()+15
  while time.monotonic()<deadline:
   value=e.one('SELECT * FROM batches WHERE id=?',(bid,))
   if value['state']==state:
    final_report=e.batch_dir(value)/'download_report.json'
    sources=files.base(e)/'literature_pdf_sources.txt'
    if state!='done' or (final_report.exists() and json.loads(final_report.read_text()).get('state')=='done' and sources.exists()):return value
   time.sleep(.05)
  raise AssertionError(('batch timeout',state,value['state'],value['error']))
 def start(p):return rpc('download.start',pmids=[p])['id']
 def prepare_slow(p):slow.add(p);entered[p]=threading.Event();release[p]=threading.Event()
 def assert_clean():
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   if not list((e.ROOT/'tmp').glob('scihub-browser-*')):return
   time.sleep(.05)
  raise AssertionError('browser temporary files not cleaned')
 try:
  rpc('storage.register',folder='BrowserTest',data={'id':e.PROJECT,'name':'Browser fixture'})
  rpc('xml.import',name='fixture.xml',xml=xml(range(1,8)))
  rpc('download.settings.save',mirrors=[f'http://127.0.0.1:{server.server_port}/entry'],fastOa=False,zoteroAddress='')
  rpc('download.settings');rpc('download.list');assert not list((e.ROOT/'tmp').glob('scihub-browser-*'))
  base=files.base(e);bid=start('1');wait(bid);assert_clean()
  assert e.one('SELECT state FROM items WHERE batch=?',(bid,))['state']=='success',e.rows('SELECT stage,outcome,detail FROM attempts WHERE batch=?',(bid,))
  asset=json.loads(e.one('SELECT data FROM assets WHERE pmid=?',('1',))['data'])
  assert asset['transport']=='playwright-chromium' and asset['source']=='Sci-Hub' and asset['sha256']==hashlib.sha256(PDF).hexdigest()
  assert asset['transferMethod']=='browser-download'
  assert not (base/'metadata/markdown-job.json').exists() and not (base/'vectors/chunks.sqlite3').exists()
  assert 'Sci-Hub' in (base/'literature_pdf_sources.txt').read_text()
  assert '1' not in (base/'literature_without_pdf.txt').read_text().splitlines()
  report=json.loads((base/'logs'/bid/'download_report.json').read_text());requests=[r for a in report['attempts'] for r in a['detail'].get('requests',[])]
  assert requests and all(r['transport']=='playwright-chromium' for r in requests)
  assert requests[0]['method']=='browser-rendered-dom'
  assert [r['requestType'] for r in requests if 'requestType' in r]==['challenge_get','challenge_post','challenge_replay']
  assert asset['identity']['status']=='match'
  assert 'private-fixture' not in json.dumps(report) and 'private-signature' not in json.dumps(report)
  print('App RPC + real worker: Altcha, JavaScript link, native attachment, identity, publication, source/cache and reports passed',flush=True)
  # Same-hash cache keeps its route and now also rechecks identity.
  (base/'pdf/1.pdf').unlink();before=len(calls);bid=start('1');wait(bid)
  report=json.loads((base/'logs'/bid/'download_report.json').read_text())
  assert any(a['detail'].get('route')=='known-file' and a['outcome']=='success' for a in report['attempts'])
  assert not any('/entry/' in v for v in calls[before:])
  bid=start('7');wait(bid);assert_clean()
  assert not (base/'pdf/7.pdf').exists()
  pending=list((base/'logs'/bid/'identity_pending/7').glob('*.pdf'));assert pending
  assert pending[0].read_bytes()==pdf(blank=True)
  report=json.loads((base/'logs'/bid/'download_report.json').read_text())
  assert any(a['detail'].get('identityPending') for a in report['attempts'])
  assert e.one('SELECT state FROM items WHERE batch=?',(bid,))['state']=='failed'
  assert '7' in (base/'literature_without_pdf.txt').read_text().splitlines()
  assert not (base/'markdown/7.md').exists() and not (base/'vectors/chunks.sqlite3').exists()
  print('Unverifiable PDF retained outside corpus; reports and downstream exclusion passed',flush=True)
  # Mutation while bytes are in flight must prevent publication.
  prepare_slow('2');bid=start('2');assert entered['2'].wait(8)
  e.atomic(base/'pubmed/current.xml',xml([1,3,4,5,6,7]));files.reconcile(e);release['2'].set();wait(bid)
  assert not (base/'pdf/2.pdf').exists();assert '生命周期' in e.one('SELECT error FROM items WHERE batch=?',(bid,))['error']
  prepare_slow('3');bid=start('3');assert entered['3'].wait(8)
  replacement=PDF+b'\n% locally replaced';e.atomic(base/'pdf/3.pdf',replacement);release['3'].set();wait(bid)
  assert (base/'pdf/3.pdf').read_bytes()==replacement
  print('Same-hash cache and removed/replaced paper publication guards passed',flush=True)
  prepare_slow('4');bid=start('4');assert entered['4'].wait(8);started=time.monotonic();rpc('download.control',id=bid,command='cancel');wait(bid,'cancelled');assert time.monotonic()-started<4;assert_clean();release['4'].set()
  assert not (base/'pdf/4.pdf').exists() and not list((base/'logs'/bid/'staging').rglob('*.pdf'))
  prepare_slow('5');bid=start('5');assert entered['5'].wait(8);rpc('download.control',id=bid,command='pause');wait(bid,'paused');assert_clean();release['5'].set();slow.remove('5')
  before=calls.count('/entry/10.1234/5');rpc('download.control',id=bid,command='resume');wait(bid);assert calls.count('/entry/10.1234/5')==before
  rpc('download.control',id=bid,command='retry');wait(bid);assert (base/'pdf/5.pdf').read_bytes()==pdf('10.1234/5')
  print('Pause/cancel cleanup, resume budget preservation and explicit retry passed',flush=True)
  # Host exit is normally set by Tauri; use its exact Python RPC owner field.
  owner=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
  prepare_slow('6')
  req={'action':'start','args':{'project':e.PROJECT,'papers':[{'pmid':'6','doi':'10.1234/6'}],'owner':owner.pid}}
  value=json.loads(subprocess.run([sys.executable,str(ROOT/'services/downloader/engine.py')],input=json.dumps(req),text=True,capture_output=True,env=env,timeout=10).stdout);assert value['ok'];bid=value['data']['id']
  assert entered['6'].wait(8);owner.terminate();owner.wait();wait(bid,'paused');assert_clean();release['6'].set();rpc('download.control',id=bid,command='cancel')
  print('Host exit pauses the independent worker and closes Chromium',flush=True)
  print(json.dumps({'success':True,'transport':asset['transport'],'chromium':asset['browserVersion'],'externalRequests':0}),flush=True)
 finally:
  for flag in release.values():flag.set()
  # Let the real worker's short idle window end before removing its isolated root.
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   lock=e.worker_lock()
   if lock:lock.close();break
   time.sleep(.05)
  server.shutdown();server.server_close()
