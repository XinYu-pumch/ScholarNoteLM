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
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'data':[{'id':m} for m in [*MODELS,'deepseek-flash','future-unknown']]}).encode())
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append({'path':self.path,'body':body,'headers':dict(self.headers)})
  if '__invalid_probe__' in json.dumps(body):
   self.send_response(422);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'error':{'param':'thinking_level','message':'invalid thinking_level'}}).encode());return
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
  deepseek_manifest=app/'services/llm_providers/deepseek/manifest.json';deepseek_meta=json.loads(deepseek_manifest.read_text());deepseek_meta['baseUrl']=base;deepseek_manifest.write_text(json.dumps(deepseek_meta))
  env={**os.environ,'SCHOLARNOTELM_ROOT':str(app)};exe=str(ROOT/'cache/tauri-target/debug/research-cli')
  def rpc(action,stream=False,**args):
   p=subprocess.run([exe]+(['--stream'] if stream else []),input=json.dumps({'action':action,'args':{'project':'test',**args}}),text=True,capture_output=True,env=env,timeout=25)
   value=json.loads(p.stdout.splitlines()[-1]);assert value.get('ok'),value
   return value['data']
  rpc('storage.initialize');rpc('storage.register',folder='ProviderTest',data={'id':'test','name':'ProviderTest','papers':[],'messages':[],'sections':[],'notes':{},'tasks':[]})
  assert 'opencode_go' in [p['id'] for p in rpc('settings')['providers']]
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
  budget_profile={**profile,'model':'qwen3.8-max','models':['qwen3.8-max'],'reasoningByModel':{'qwen3.8-max':'budget'},'reasoningBudgetByModel':{'qwen3.8-max':262144}}
  budget_saved=rpc('profile.save',profile=budget_profile)
  assert rpc('llm.test',profile=budget_saved)['reply']
  assert requests[-1]['body']['thinking']=={'type':'enabled','budget_tokens':262144}
  assert 'output_config' not in requests[-1]['body']
  for budget in [None,0,-1,1.5,True,262145]:
   invalid={**budget_profile,'reasoningBudgetByModel':{'qwen3.8-max':budget}}
   failed=subprocess.run([exe],input=json.dumps({'action':'profile.save','args':{'profile':invalid}}),text=True,capture_output=True,env=env,timeout=10)
   assert not json.loads(failed.stdout)['ok']
  normal={'id':'ordinary','name':'opencode_go','baseUrl':base,'model':'normal','models':['normal'],'temperature':None,'timeout':10}
  rpc('profile.save',profile=normal,makeDefault=True);rpc('llm.test',profile=normal);assert 'x-opencode-session' not in headers(requests[-1])
  deepseek={'id':'ds','provider':'deepseek','name':'DeepSeek','baseUrl':base,'model':'deepseek-flash','models':['deepseek-flash'],'reasoningByModel':{'deepseek-flash':'low'},'temperature':None,'timeout':10}
  saved_ds=rpc('profile.save',profile=deepseek);assert rpc('llm.models',profile=saved_ds)==['deepseek-flash']
  assert rpc('llm.test',profile=saved_ds)['reply'];assert requests[-1]['body']['reasoning_effort']=='low';assert 'x-opencode-session' not in headers(requests[-1])
  ds_thread=rpc('chat.new',name='DeepSeek search');ds_history=rpc('chat',stream=True,chatId=ds_thread['id'],streamId=uuid.uuid4().hex,profileId='ds',message='Design a search')
  assert not ds_history[-1]['error'] and ds_history[-1]['result']['queries'];assert 'x-opencode-session' not in headers(requests[-1])
  shutil.rmtree(manifest.parent)  # Simulate uninstall while keeping stored Go profiles.
  assert 'opencode_go' not in [p['id'] for p in rpc('settings')['providers']]
  rpc('profile.save',profile=normal)
  failed=subprocess.run([exe],input=json.dumps({'action':'llm.test','args':{'profileId':'go-0'}}),text=True,capture_output=True,env=env,timeout=10)
  assert not json.loads(failed.stdout)['ok']
  assert rpc('llm.test',profile=saved_ds)['reply'];assert 'x-opencode-session' not in headers(requests[-1])
  assert rpc('llm.test',profile=normal)['reply'];assert 'x-opencode-session' not in headers(requests[-1])
  thread=rpc('chat.new',name='ordinary');h=rpc('chat',stream=True,chatId=thread['id'],streamId=uuid.uuid4().hex,profileId='ordinary',message='Still works');assert not h[-1]['error']
  # Explicit presets remain usable after the Go module is physically removed.
  assert {p['id'] for p in rpc('settings')['thinkingPresets']}=={p['id'] for p in json.loads((ROOT/'services/downloader/thinking_presets.json').read_text())}
  catalog=json.loads((ROOT/'services/downloader/thinking_presets.json').read_text())
  for spec in catalog:
   preset=spec['id'];level={'generic_effort':'xhigh','generic_thinking_toggle':'disabled','qwen_openai':'medium','glm_openai':'max'}.get(preset,spec['defaultLevel'])
   custom={**normal,'id':'preset-'+preset,'name':preset,'thinkingByModel':{'normal':{'preset':preset,'level':level}},'temperature':0.2}
   saved_custom=rpc('profile.save',profile=custom)
   assert saved_custom['thinkingByModel']==custom['thinkingByModel']
   assert rpc('llm.test',profileId=custom['id'])['reply']
   thread=rpc('chat.new',name=preset)
   h=rpc('chat',stream=True,chatId=thread['id'],streamId=uuid.uuid4().hex,profileId=custom['id'],message='Search PLA2R')
   assert not h[-1]['error'] and h[-1]['result']['queries']
   observed=requests[-1];assert 'x-opencode-session' not in headers(observed)
   if preset=='gemini4_native':
    assert observed['path']=='/v1beta/models/normal:streamGenerateContent?alt=sse'
    assert observed['body']['generationConfig']['thinkingConfig']=={'thinkingLevel':level,'includeThoughts':True}
   elif preset=='claude55_messages':
    assert observed['path']=='/v1/messages' and observed['body']['output_config']['effort']==level
   elif spec['protocol']=='responses':
    assert observed['path']=='/v1/responses' and observed['body']['reasoning']==spec['options'][level]['reasoning']
   elif preset=='claude55_chat':
    assert observed['body']['thinking']=={'type':'adaptive'} and 'reasoning_effort' not in observed['body']
   elif preset in ('generic_thinking_toggle','mimo_v26_openai'):
    assert observed['body']['thinking']=={'type':level} and 'reasoning_effort' not in observed['body']
   else:
    assert observed['body']['reasoning_effort']==level
    if preset=='qwen_openai':assert observed['body']['enable_thinking'] is True and 'extra_body' not in observed['body']
    if preset=='deepseek_openai':assert observed['body']['thinking']=={'type':'enabled'} and 'temperature' not in observed['body']
   invalid={**custom,'thinkingByModel':{'normal':{'preset':preset,'level':'invalid'}}}
   failed=subprocess.run([exe],input=json.dumps({'action':'profile.save','args':{'profile':invalid}}),text=True,capture_output=True,env=env,timeout=10)
   assert not json.loads(failed.stdout)['ok']
  output_profile={**normal,'id':'summary-test','name':'Summary fixture','thinkingByModel':{'normal':{'preset':'gemini4_openai','level':'high','output':'summary'}}}
  saved_output=rpc('profile.save',profile=output_profile)
  assert saved_output['thinkingByModel']==output_profile['thinkingByModel']
  count=len(requests)
  report=rpc('llm.test',profile={**saved_output,'testThinkingProbe':True})
  assert len(requests)==count+2 and report['thinking']['probe']['status']=='rejected'
  assert requests[-2]['body']['extra_body']=={'google':{'thinking_config':{'thinking_level':'high','include_thoughts':True}}}
  assert 'reasoning_effort' not in requests[-2]['body']
  assert rpc('profile.list')['profiles'][-1]['thinkingByModel']==output_profile['thinkingByModel']
  for mode in ['invalid',None,True]:
   invalid={**output_profile,'thinkingByModel':{'normal':{'preset':'gemini4_openai','level':'high','output':mode}}}
   failed=subprocess.run([exe],input=json.dumps({'action':'profile.save','args':{'profile':invalid}}),text=True,capture_output=True,env=env,timeout=10)
   assert not json.loads(failed.stdout)['ok']
  print(json.dumps({'passed':True,'protocols':4,'checks':['Rust profile persistence and public redaction','known model catalog filtering','Python connection tests','Rust multi-turn search through private worker','stable sessions and independent conversations','silent stream cancellation','ordinary profile named opencode_go has no special headers','physical adapter removal leaves ordinary Python and Rust calls working']},ensure_ascii=False))
finally:server.shutdown();server.server_close()
