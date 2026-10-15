"""Rust RPC + private Python worker, four protocols, removal and cancellation.

No live services. Copies code into a temporary root and replaces ONLY the copied
provider manifest's official URL with the loopback fixture endpoint.
"""
import json,os,shutil,subprocess,tempfile,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];requests=[];slow_started=threading.Event()
MODELS=['deepseek-v4.1-flash','gemini-4-argon-contributor','gpt-6-luna','claude-haiku-5-5']
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'data':[{'id':m} for m in [*MODELS,'future-unknown']]}).encode())
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append({'path':self.path,'body':body,'headers':dict(self.headers)})
  text='### 基础检索\n\n```pubmed\nPLA2R[tiab]\n```'
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  if 'CANCEL_FIXTURE' in json.dumps(body):slow_started.set();time.sleep(3)
  if ':streamGenerateContent' in self.path:events=[{'candidates':[{'content':{'parts':[{'text':text}]},'finishReason':'STOP'}]}]
  elif self.path.endswith('/responses'):events=[{'type':'response.output_text.delta','delta':text},{'type':'response.completed','response':{'status':'completed','output':[]}}]
  elif self.path.endswith('/messages'):events=[{'type':'content_block_delta','delta':{'type':'text_delta','text':text}},{'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}]
  else:events=[{'choices':[{'delta':{'content':text},'finish_reason':'stop'}]}]
  try:
   for event in events:self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with tempfile.TemporaryDirectory(prefix='provider-integration-',dir=ROOT/'tmp') as folder:
  app=Path(folder);(app/'tmp').mkdir();(app/'runtimes').symlink_to(ROOT/'runtimes',target_is_directory=True)
  shutil.copytree(ROOT/'services/downloader',app/'services/downloader',ignore=shutil.ignore_patterns('__pycache__','tests'))
  shutil.copytree(ROOT/'services/llm_providers',app/'services/llm_providers',ignore=shutil.ignore_patterns('__pycache__'))
  manifest=app/'services/llm_providers/opencode_go/manifest.json';meta=json.loads(manifest.read_text());base=f'http://127.0.0.1:{server.server_port}/v1';meta['baseUrl']=base;manifest.write_text(json.dumps(meta))
  env={**os.environ,'SCHOLARNOTELM_ROOT':str(app)};exe=str(ROOT/'cache/tauri-target/debug/research-cli')
  def rpc(action,stream=False,**args):
   p=subprocess.run([exe]+(['--stream'] if stream else []),input=json.dumps({'action':action,'args':{'project':'test',**args}}),text=True,capture_output=True,env=env,timeout=25)
   value=json.loads(p.stdout.splitlines()[-1]);assert value.get('ok'),value
   return value['data']
  rpc('storage.initialize');rpc('storage.register',folder='ProviderTest',data={'id':'test','name':'ProviderTest','papers':[],'messages':[],'sections':[],'notes':{},'tasks':[]})
  assert rpc('settings')['providers'][0]['id']=='opencode_go'
  reasoning=dict(zip(MODELS,['max','medium','high','xhigh']))
  for index,model in enumerate(MODELS):
   profile={'id':'go-0','provider':'opencode_go','name':f'Go {index}','baseUrl':base,'apiKey':'fixture-secret','model':model,'models':MODELS,'reasoningByModel':reasoning,'temperature':None,'timeout':10}
   saved=rpc('profile.save',profile=profile);assert saved['provider']=='opencode_go' and saved['hasKey'] and 'apiKey' not in saved
   assert saved['name']=='opencode_go' and saved['reasoningByModel']==reasoning
   assert rpc('llm.models',profile=saved)==MODELS
   assert rpc('llm.test',profile=saved)['reply']
   thread=rpc('chat.new',name='test');start=len(requests)
   for message in ['Design a search','Include THSD7A']:
    history=rpc('chat',stream=True,chatId=thread['id'],streamId=uuid.uuid4().hex,profileId=saved['id'],message=message)
    assert not history[-1]['error'] and history[-1]['result']['queries'],history[-1]
   assert len(requests)==start+2
   body=requests[-1]['body']
   if index==0:assert body['reasoning_effort']=='max' and body['thinking']['type']=='enabled'
   elif index==1:assert body['generationConfig']['thinkingConfig']['thinkingLevel']=='medium'
   elif index==2:assert body['reasoning']['effort']=='high'
   else:assert body['output_config']['effort']=='xhigh' and body['thinking']['type']=='adaptive'
   a,b=requests[-2:];headers=lambda r:{k.lower():v for k,v in r['headers'].items()}
   assert headers(a)['x-opencode-session']==headers(b)['x-opencode-session'];assert headers(a)['user-agent']=='ScholarNoteLM/0.6.0'
   assert 'Design a search' in json.dumps(b['body']) and 'PLA2R[tiab]' in json.dumps(b['body'])
   independent=rpc('chat.new',name='independent');rpc('chat',stream=True,chatId=independent['id'],streamId=uuid.uuid4().hex,profileId=saved['id'],message='Independent search')
   assert headers(requests[-1])['x-opencode-session']!=headers(a)['x-opencode-session']
  # Backend singleton enforcement also covers stale/new clients bypassing the UI.
  failed=subprocess.run([exe],input=json.dumps({'action':'profile.save','args':{'profile':{**profile,'id':'second-go'}}}),text=True,capture_output=True,env=env,timeout=10)
  assert not json.loads(failed.stdout)['ok'] and '一个配置' in json.loads(failed.stdout)['error']
  assert len([p for p in rpc('profile.list')['profiles'] if p.get('provider')=='opencode_go'])==1
  # Cancellation must drop the private worker even while the upstream is silent.
  thread=rpc('chat.new',name='cancel');sid=uuid.uuid4().hex
  child=subprocess.Popen([exe,'--stream'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
  child.stdin.write(json.dumps({'action':'chat','args':{'project':'test','chatId':thread['id'],'streamId':sid,'profileId':'go-0','message':'CANCEL_FIXTURE'}}));child.stdin.close()
  assert slow_started.wait(10);start=time.monotonic();rpc('chat.cancel',streamId=sid)
  child.wait(timeout=3);assert time.monotonic()-start<2;history=rpc('chat.get',id=thread['id'])['messages'];assert history[-1]['cancelled']
  normal={'id':'ordinary','name':'opencode_go','baseUrl':base,'model':'normal','models':['normal'],'temperature':None,'timeout':10}
  rpc('profile.save',profile=normal,makeDefault=True);rpc('llm.test',profile=normal);assert 'x-opencode-session' not in headers(requests[-1])
  shutil.rmtree(manifest.parent)  # Simulate uninstall while keeping stored Go profiles.
  assert rpc('settings')['providers']==[]
  rpc('profile.save',profile=normal)
  failed=subprocess.run([exe],input=json.dumps({'action':'llm.test','args':{'profileId':'go-0'}}),text=True,capture_output=True,env=env,timeout=10)
  assert not json.loads(failed.stdout)['ok']
  assert rpc('llm.test',profile=normal)['reply'];assert 'x-opencode-session' not in headers(requests[-1])
  thread=rpc('chat.new',name='ordinary');h=rpc('chat',stream=True,chatId=thread['id'],streamId=uuid.uuid4().hex,profileId='ordinary',message='Still works');assert not h[-1]['error']
  print(json.dumps({'passed':True,'protocols':4,'checks':['Rust profile persistence and public redaction','known model catalog filtering','Python connection tests','Rust multi-turn search through private worker','stable sessions and independent conversations','silent stream cancellation','ordinary profile named opencode_go has no special headers','physical adapter removal leaves ordinary Python and Rust calls working']},ensure_ascii=False))
finally:server.shutdown();server.server_close()
