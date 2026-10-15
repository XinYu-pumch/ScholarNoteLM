"""Provider wire contracts and default-path isolation; no live requests."""
import asyncio,copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx,llm_provider as providers,review_llm as llm,review_writing,qa_service,vector_chunks

class Bytes(httpx.AsyncByteStream):
 def __init__(self,events):self.events=events
 async def __aiter__(self):
  for event in self.events:yield ('data: '+json.dumps(event)+'\n\n').encode()

class ProviderTests(unittest.IsolatedAsyncioTestCase):
 def profile(self,model):
  p={'id':'p','provider':'opencode_go','baseUrl':'https://opencode.ai/inference/go/v1','model':model,'apiKey':'fixture-secret','temperature':None,'timeout':10}
  p['endpoint']=providers.endpoint(p,llm.endpoint);return providers.with_session(p,'qa','project','thread')
 def client(self,handler):
  real=httpx.AsyncClient
  return patch.object(llm.httpx,'AsyncClient',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
 async def test_all_native_protocols_and_headers(self):
  cases=[('deepseek-v4.1-flash','/chat/completions',[{'choices':[{'delta':{'reasoning_content':'thinking'}}]},{'choices':[{'delta':{'content':'hello'},'finish_reason':'stop'}]}]),
   ('gemini-4-argon-contributor',':streamGenerateContent',[{'candidates':[{'content':{'parts':[{'text':'thinking','thought':True}]}}]},{'candidates':[{'content':{'parts':[{'text':'hello'}]},'finishReason':'STOP'}]}]),
   ('gpt-6-luna','/responses',[{'type':'response.reasoning_summary_text.delta','delta':'thinking'},{'type':'response.output_text.delta','delta':'hello'},{'type':'response.completed','response':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'hello'}]}]}}]),
   ('minimax-m2.7','/messages',[{'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'thinking'}},{'type':'content_block_delta','delta':{'type':'text_delta','text':'hello'}},{'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}])]
  for model,path,events in cases:
   with self.subTest(model=model):
    requests=[];thought=[]
    async def handler(req):requests.append(req);return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Bytes(events))
    messages=[{'role':'system','content':'rules'},{'role':'user','content':'first'},{'role':'assistant','content':'previous'},{'role':'user','content':'next'}]
    p=self.profile(model)
    with self.client(handler),patch.object(llm,'system_proxy',return_value=None):result=await llm.chat(p,messages,lambda:False,on_reasoning=thought.append)
    self.assertEqual(result,'hello');self.assertEqual(thought[-1],'thinking');req=requests[0];self.assertIn(path,str(req.url));self.assertEqual(req.headers['x-opencode-session'],p['_session']);self.assertEqual(req.headers['user-agent'],'ScholarNoteLM/0.6.0');self.assertEqual(req.headers['authorization'],'Bearer fixture-secret')
    body=json.loads(req.content);self.assertIn('previous',json.dumps(body))
    if path==':streamGenerateContent':self.assertEqual(body['generationConfig'],{'thinkingConfig':{'includeThoughts':True}})
    else:self.assertNotIn('includeThoughts',json.dumps(body))
    if path=='/messages':self.assertEqual(body['max_tokens'],131072);self.assertEqual(req.headers['anthropic-version'],'2023-06-01')
    else:self.assertFalse({'max_tokens','max_completion_tokens','max_output_tokens'}&set(body))
 async def test_default_profile_never_loads_plugin_or_adds_headers(self):
  requests=[]
  async def handler(req):requests.append(req);return httpx.Response(200,json={'choices':[{'message':{'content':'normal'}}]})
  p={'name':'opencode_go','model':'gemini-4-argon-contributor','apiKey':'fixture-key','endpoint':'https://normal.invalid/v1/chat/completions','reasoningByModel':{'gemini-4-argon-contributor':'high'}}
  with self.client(handler),patch.object(providers,'_load',side_effect=AssertionError('default loaded plugin')),patch.object(llm,'system_proxy',return_value=None):
   self.assertEqual(await llm.chat(p,[{'role':'user','content':'normal'}],lambda:False),'normal')
  self.assertNotIn('x-opencode-session',requests[0].headers);self.assertNotEqual(requests[0].headers['user-agent'],'ScholarNoteLM/0.6.0');self.assertEqual(json.loads(requests[0].content),{'model':p['model'],'messages':[{'role':'user','content':'normal'}],'stream':True})
 async def test_incomplete_native_stream_and_output_limits_are_failures(self):
  cases=[('gpt-6-luna',[{'type':'response.output_text.delta','delta':'partial'}]),('gemini-4-argon-contributor',[{'candidates':[{'content':{'parts':[{'text':'partial'}]},'finishReason':'MAX_TOKENS'}]}]),('minimax-m2.7',[{'type':'content_block_delta','delta':{'text':'partial'}},{'type':'message_delta','delta':{'stop_reason':'max_tokens'}},{'type':'message_stop'}]),('gpt-6-luna',[{'type':'response.incomplete','response':{'status':'incomplete'}}])]
  for model,events in cases:
   with self.subTest(model=model):
    async def handler(req):return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Bytes(events))
    with self.client(handler),patch.object(llm,'system_proxy',return_value=None),self.assertRaises(ValueError):await llm.chat(self.profile(model),[],lambda:False)
 def test_image_mapping_and_system_messages(self):
  messages=[{'role':'system','content':'rules'},{'role':'user','content':[{'type':'text','text':'look'},{'type':'image_url','image_url':{'url':'data:image/png;base64,aGVsbG8='}}]}]
  for model in ['gemini-4-argon-contributor','minimax-m2.7','gpt-6-luna']:
   p=self.profile(model);url,body,headers,decoder=providers.adapter(p).prepare(p,messages)
   self.assertIn('aGVsbG8=',json.dumps(body));self.assertIn('image/png',json.dumps(body));self.assertIn('rules',json.dumps(body))
 def test_missing_adapter_and_unknown_model_fail_closed(self):
  with tempfile.TemporaryDirectory() as root,patch.object(providers,'DIRECTORY',Path(root)):
   self.assertIsNone(providers.adapter({}));self.assertEqual(providers.endpoint({'baseUrl':'https://normal.invalid'},llm.endpoint),'https://normal.invalid/v1/chat/completions')
   with self.assertRaisesRegex(ValueError,'停用'):providers.adapter({'provider':'opencode_go'})
  with self.assertRaisesRegex(ValueError,'官方端点'):self.profile('future-unknown-model')
  p=self.profile('deepseek-v4.1-flash');p['baseUrl']='https://other.invalid'
  with self.assertRaises(ValueError):providers.adapter(p).prepare(p,[])
 def test_sessions_stay_stable_but_separate_threads_and_units(self):
  p={'provider':'opencode_go'};a=providers.with_session(p,'qa','project','thread');self.assertEqual(a,providers.with_session(p,'qa','project','thread'))
  self.assertNotEqual(a['_session'],providers.with_session(p,'qa','project','fork')['_session'])
  self.assertNotEqual(providers.with_session(p,'writing','p','review','round','1'),providers.with_session(p,'writing','p','review','round','2'))
  self.assertIs(providers.with_session(p:={},'qa','p','t'),p)
 def test_per_model_effort_routes_and_rejects_invalid_levels(self):
  for info in providers.manifest({'provider':'opencode_go'})['models'].values():self.assertEqual(info['reasoning']['levels'],list(info['reasoning']['options']))
  selected={'deepseek-v4.1-flash':'max','gemini-4-argon-contributor':'medium','gpt-6-luna':'xhigh','claude-haiku-5-5':'high','qwen3.8-max':'xhigh'}
  expected=[('deepseek-v4.1-flash',{'reasoning_effort':'max','thinking':{'type':'enabled'}}),
   ('gemini-4-argon-contributor',{'generationConfig':{'thinkingConfig':{'thinkingLevel':'medium','includeThoughts':True}}}),
   ('gpt-6-luna',{'reasoning':{'effort':'xhigh'}}),
   ('claude-haiku-5-5',{'thinking':{'type':'adaptive'},'output_config':{'effort':'high'}}),
   ('qwen3.8-max',{'thinking':{'type':'enabled'},'output_config':{'effort':'xhigh'}})]
  for model,fields in expected:
   p={**self.profile(model),'reasoningByModel':selected}
   _,body,_,_=providers.adapter(p).prepare(p,[])
   for key,value in fields.items():self.assertEqual(body[key],value)
  p={**self.profile('gemini-4-argon-contributor'),'temperature':.5,'reasoningByModel':selected}
  self.assertEqual(providers.adapter(p).prepare(p,[])[1]['generationConfig'],{'temperature':.5,'thinkingConfig':{'thinkingLevel':'medium','includeThoughts':True}})
  for model,level in [('deepseek-v4.1-flash','medium'),('deepseek-v4-pro','low'),('gemini-4-argon-contributor','max'),('minimax-m2.7','high'),('gpt-6-luna',None)]:
   p={**self.profile(model),'reasoningByModel':{model:level}}
   with self.assertRaises(ValueError):providers.adapter(p).prepare(p,[])
  p=self.profile('deepseek-v4.1-flash');module=providers.adapter(p)
  self.assertEqual(module.prepare(p,[])[1],module.prepare({**p,'reasoningByModel':{'gemini-4-argon-contributor':'high'}},[])[1])
  self.assertEqual(module.prepare(p,[])[1],module.prepare({**p,'reasoningByModel':{p['model']:''}},[])[1])
 def test_reasoning_signature_changes_only_for_selected_model(self):
  for fn in [review_writing.profile_signature,qa_service.profile_signature]:
   p=self.profile('deepseek-v4.1-flash');original=fn(p)
   self.assertEqual(fn({**p,'reasoningByModel':{}}),original)
   self.assertEqual(fn({**p,'reasoningByModel':{'gemini-4-argon-contributor':'high'}}),original)
   self.assertNotEqual(fn({**p,'reasoningByModel':{p['model']:'max'}}),original)
   normal={**p,'provider':'openai'}
   self.assertEqual(fn(normal),fn({**normal,'reasoningByModel':{p['model']:'max'}}))
 def test_legacy_signatures_unchanged_and_provider_is_distinct(self):
  p={'id':'p','model':'m','baseUrl':'https://host/v1','endpoint':'https://host/v1/chat/completions'}
  for fn,keys in [(review_writing.profile_signature,('id','model','endpoint','temperature','sendTemperature','visionModels')),(qa_service.profile_signature,('id','model','baseUrl','temperature','timeout','apiKey','sendTemperature','visionModels'))]:
   expected=vector_chunks.digest({k:p.get(k) for k in keys});self.assertEqual(fn(p),expected);self.assertEqual(fn({**p,'provider':'openai'}),expected);self.assertNotEqual(fn({**p,'provider':'opencode_go'}),expected)
 async def test_connection_retry_reuses_session_and_cancellation_is_prompt(self):
  seen=[]
  async def handler(req):
   seen.append(req.headers['x-opencode-session'])
   if len(seen)==1:raise httpx.ConnectError('transient')
   return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Bytes([{'choices':[{'delta':{'content':'ok'},'finish_reason':'stop'}]}]))
  with self.client(handler),patch.object(llm,'system_proxy',return_value=None):self.assertEqual(await llm.chat(self.profile('deepseek-v4.1-flash'),[],lambda:False),'ok')
  self.assertEqual(len(seen),2);self.assertEqual(seen[0],seen[1])
  cancelled=False
  class Slow(httpx.AsyncByteStream):
   async def __aiter__(self):
    nonlocal cancelled
    yield b'data: {"candidates":[{"content":{"parts":[{"text":"partial"}]}}]}\n\n';cancelled=True;await asyncio.sleep(60)
  async def slow(req):return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Slow())
  with self.client(slow),patch.object(llm,'system_proxy',return_value=None),self.assertRaises(llm.Cancelled):await asyncio.wait_for(llm.chat(self.profile('gemini-4-argon-contributor'),[],lambda:cancelled),2)

if __name__=='__main__':unittest.main()
