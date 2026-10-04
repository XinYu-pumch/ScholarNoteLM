"""Isolated real-Rust credential lifecycle; never reads user keys."""
import json,os,sqlite3,subprocess,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
seen=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append((self.path,self.headers.get('Authorization')))
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  self.wfile.write(b'data: {"choices":[{"delta":{"content":"connection OK"}}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
 def do_GET(self):
  seen.append((self.path,self.headers.get('Authorization')));self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"data":[{"id":"fixture-model"}]}')
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
proxy_hits=[]
class BrokenProxy(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def fail(self):proxy_hits.append(self.path);self.send_response(502);self.end_headers()
 def do_GET(self):self.fail()
 def do_POST(self):self.rfile.read(int(self.headers['Content-Length']));self.fail()
proxy=ThreadingHTTPServer(('127.0.0.1',0),BrokenProxy);threading.Thread(target=proxy.serve_forever,daemon=True).start()
network_env={}
try:
 with tempfile.TemporaryDirectory(prefix='model-settings-',dir=ROOT/'tmp') as tmp:
  app=Path(tmp);(app/'runtimes').mkdir();(app/'services').symlink_to(ROOT/'services',target_is_directory=True);(app/'runtimes/downloader').symlink_to(ROOT/'runtimes/downloader',target_is_directory=True)
  def rpc(action,**args):
   proc=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':args}),capture_output=True,text=True,env={**os.environ,**network_env,'SCHOLARNOTELM_ROOT':tmp})
   result=json.loads(proc.stdout)
   if not result['ok']:raise RuntimeError(result['error'])
   return result['data']
  rpc('pubmed.save',email='fixture@example.com',apiKey='fixture-ncbi-key')
  assert rpc('pubmed.key')['apiKey']=='fixture-ncbi-key'
  rpc('pubmed.save',email='changed@example.com',apiKey='')
  assert rpc('pubmed.key')['apiKey']=='fixture-ncbi-key'
  rpc('pubmed.save',email='changed@example.com',apiKey='',clearKey=True)
  assert rpc('pubmed.key')['apiKey']==''
  p={'id':'','name':' Fixture ','baseUrl':f' http://127.0.0.1:{server.server_port}/v1/chat/completions/ ','model':'','apiKey':' fixture-secret ','timeout':120,'temperature':None}
  saved=rpc('profile.save',profile=p);assert saved['hasKey'] and saved['model']=='' and saved['name']=='Fixture'
  assert saved['baseUrl']==f'http://127.0.0.1:{server.server_port}/v1'
  assert 'apiKey' not in saved and 'clearKey' not in saved
  assert rpc('profile.key',id=saved['id'])['apiKey']=='fixture-secret'
  assert rpc('profile.list')['profiles']==[saved]
  assert rpc('llm.models',profile=saved)==['fixture-model']
  assert seen[-1]==('/v1/models','Bearer fixture-secret')
  saved=rpc('profile.save',profile={**saved,'model':'fixture-model','apiKey':'   ','visionModels':['fixture-model']});assert saved['hasKey'];assert saved['visionModels']==['fixture-model'];assert rpc('profile.list')['profiles'][0]['visionModels']==['fixture-model']
  assert rpc('profile.key',id=saved['id'])['apiKey']=='fixture-secret'
  saved=rpc('profile.save',profile={**saved,'apiKey':'replacement'});assert rpc('profile.key',id=saved['id'])['apiKey']=='replacement'
  saved=rpc('profile.save',profile={**saved,'clearKey':True});assert not saved['hasKey']
  assert rpc('profile.key',id=saved['id'])['apiKey']=='' and 'clearKey' not in saved
  saved=rpc('profile.save',profile={**saved,'apiKey':'restored'});assert saved['hasKey'] and rpc('profile.key',id=saved['id'])['apiKey']=='restored'
  result=rpc('llm.test',profile={**saved,'baseUrl':f'http://127.0.0.1:{server.server_port}/v1/chat/completions'});assert result['reply']=='connection OK' and result['client']=='qa-stream' and result['model']=='fixture-model'
  assert seen[-1]==('/v1/chat/completions','Bearer restored')
  safe=json.dumps(rpc('profile.list'));assert 'restored' not in safe
  proxy_url=f'http://127.0.0.1:{proxy.server_port}'
  network_env.update({k:proxy_url for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')});network_env.update(NO_PROXY='',no_proxy='')
  saved=rpc('profile.save',profile={**saved,'networkMode':'system'})
  assert 'networkMode' not in saved and 'networkMode' not in rpc('profile.list')['profiles'][0]
  for profile in (saved,{**saved,'networkMode':'system'}):
   assert rpc('llm.models',profile=profile)==['fixture-model']
   result=rpc('llm.test',profile=profile);assert result['networkMode']=='direct' and result['reply']=='connection OK'
  assert proxy_hits==[],proxy_hits
  print(json.dumps({'success':True,'checks':['save API before selecting model','normalize complete endpoint','masked list and save responses','explicit key reveal','blank preserves key','replace and clear key','clear flag not persisted','model discovery uses saved credential','legacy network setting removed','model discovery and streaming always bypass broken proxy']},ensure_ascii=False))
finally:
 for srv in (server,proxy):srv.shutdown();srv.server_close()
