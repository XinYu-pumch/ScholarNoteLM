"""Synthetic wire tests: output controls, evidence strength, and safe diagnostics."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx,review_llm as llm,llm_thinking as thinking,llm_provider

class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.profile={'baseUrl':'https://relay.invalid/v1','model':'model','apiKey':'secret-fixture',
                'thinkingByModel':{'model':{'preset':'gemini4_native','level':'high','output':'summary'}}}
  self.client=httpx.AsyncClient
  proxy=patch.object(llm,'system_proxy',return_value=None);proxy.start();self.addCleanup(proxy.stop)
 def mock(self,handler):
  return patch.object(llm.httpx,'AsyncClient',side_effect=lambda **kwargs:self.client(transport=httpx.MockTransport(handler),**kwargs))
 def test_summary_wire_and_legacy_signatures(self):
  original=copy.deepcopy(self.profile)
  for mode in ('summary','off'):
   p=copy.deepcopy(original);p['thinkingByModel']['model']['output']=mode
   url,body,headers,_=thinking.prepare(p,[])
   self.assertEqual(url,'https://relay.invalid/v1beta/models/model:streamGenerateContent?alt=sse')
   self.assertEqual(body['generationConfig']['thinkingConfig'],{'thinkingLevel':'high','includeThoughts':mode=='summary'})
   self.assertNotIn('reasoning_effort',body);self.assertNotIn('x-opencode-session',headers)
  old=copy.deepcopy(original);old['thinkingByModel']['model'].pop('output')
  default=copy.deepcopy(old);default['thinkingByModel']['model']['output']='default'
  self.assertEqual(thinking.prepare(old,[])[1],thinking.prepare(default,[])[1])
  self.assertEqual(llm_provider.signature_fields(old,()),llm_provider.signature_fields(default,()))
  self.assertNotEqual(llm_provider.signature_fields(old,()),llm_provider.signature_fields(original,()))
  other=copy.deepcopy(old);other['thinkingByModel']['other']={'preset':'gemini4_native','level':'low','output':'summary'}
  self.assertEqual(llm_provider.signature_fields(old,()),llm_provider.signature_fields(other,()))
  self.assertNotIn('extra_body',thinking.prepare(old,[])[1])
 def test_native_output_default_preserves_summary(self):
  p=copy.deepcopy(self.profile);p['thinkingByModel']['model']['preset']='gemini4_native'
  for mode,expected in [('default',True),('summary',True),('off',False)]:
   p['thinkingByModel']['model']['output']=mode
   self.assertEqual(thinking.prepare(p,[])[1]['generationConfig']['thinkingConfig']['includeThoughts'],expected)
 def test_no_summary_switch_in_non_google_presets(self):
  for preset in ['deepseek_openai','qwen_openai','glm_openai','generic_thinking_toggle']:
   p=copy.deepcopy(self.profile);p['thinkingByModel']['model'].update(preset=preset,level=thinking.PRESETS[preset]['defaultLevel'])
   with self.assertRaisesRegex(ValueError,'输出方式'):thinking.prepare(p,[])
 async def test_stream_observes_summary_and_trailing_usage(self):
  requests=[]
  async def handler(req):
   requests.append(json.loads(req.content))
   events=[{'candidates':[{'content':{'parts':[{'text':'summary','thought':True}]}}]},
           {'candidates':[{'content':{'parts':[{'text':'9/38'}]},'finishReason':'STOP'}]},
           {'usageMetadata':{'thoughtsTokenCount':42}}]
   return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=''.join('data: '+json.dumps(v)+'\n\n' for v in events)+'data: [DONE]\n\n')
  with self.mock(handler):result=await llm.test_connection(self.profile)
  self.assertEqual(len(requests),1);self.assertEqual(result['reply'],'9/38')
  self.assertEqual(result['thinking']['reasoningCharacters'],7);self.assertEqual(result['thinking']['reasoningTokens'],42)
  self.assertEqual(result['thinking']['outputKind'],'summary')
  self.assertNotIn('secret-fixture',json.dumps(result));self.assertNotIn('messages',json.dumps(result['thinking']))
 async def test_probe_rejection_acceptance_and_ambiguous_errors(self):
  original=copy.deepcopy(self.profile)
  for status,error,expected in [(422,{'param':'thinkingLevel','message':'invalid'},'rejected'),
    (400,{'message':'thinkingLevel must be one of low medium high'},'rejected'),
    (400,{'message':'bad request secret-fixture'},'inconclusive'),
    (429,{'param':'thinkingLevel','message':'rate limit secret-fixture'},'inconclusive'),
    (500,{'param':'thinkingLevel'},'inconclusive'),(200,None,'accepted')]:
   requests=[]
   async def handler(req):
    body=json.loads(req.content);requests.append(body)
    if len(requests)==2 and status!=200:return httpx.Response(status,json={'error':error})
    return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'9/38'}]},'finishReason':'STOP'}]})
   with self.mock(handler):result=await llm.test_connection({**self.profile,'testThinkingProbe':True})
   self.assertEqual(len(requests),2);self.assertEqual(result['thinking']['probe']['status'],expected)
   self.assertNotIn('secret-fixture',json.dumps(result))
   self.assertEqual(requests[1]['generationConfig']['thinkingConfig']['thinkingLevel'],'__invalid_probe__')
   requests[1]['generationConfig']['thinkingConfig']['thinkingLevel']='high'
   self.assertEqual(requests[0],requests[1]);self.assertEqual(self.profile,original)
 async def test_bool_probe_and_no_probe_for_server_default(self):
  for level,count in [('disabled',2),('default',1)]:
   requests=[]
   p={**self.profile,'thinkingByModel':{'model':{'preset':'qwen_openai','level':level}},'testThinkingProbe':True}
   async def handler(req):
    requests.append(json.loads(req.content))
    return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
   with self.mock(handler):result=await llm.test_connection(p)
   self.assertEqual(len(requests),count)
   if count==2:self.assertEqual(requests[1]['enable_thinking'],{'invalid':'__invalid_probe__'})
   else:self.assertEqual(result['thinking']['probe']['status'],'not_applicable')
 async def test_missing_reasoning_is_not_failure_or_zero_usage(self):
  async def handler(req):return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'ok'}]},'finishReason':'STOP'}]})
  with self.mock(handler):result=await llm.test_connection(self.profile)
  self.assertEqual(result['thinking']['reasoningCharacters'],0);self.assertIsNone(result['thinking']['reasoningTokens'])
 async def test_normal_failure_never_triggers_negative_probe(self):
  calls=[]
  async def handler(req):calls.append(req);return httpx.Response(401,json={'error':{'message':'secret-fixture'}})
  with self.mock(handler),self.assertRaises(llm.UpstreamFailure) as caught:await llm.test_connection({**self.profile,'testThinkingProbe':True})
  self.assertEqual(len(calls),1);self.assertNotIn('secret-fixture',str(caught.exception))
 async def test_native_probe_and_usage(self):
  p=copy.deepcopy(self.profile);p['thinkingByModel']['model']['preset']='gemini4_native';p['testThinkingProbe']=True
  calls=[]
  async def handler(req):
   body=json.loads(req.content);calls.append(body)
   if len(calls)==2:return httpx.Response(400,json={'error':{'message':'Invalid thinkingLevel __invalid_probe__'}})
   return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'summary','thought':True},{'text':'ok'}]},'finishReason':'STOP'}],'usageMetadata':{'thoughtsTokenCount':12}})
  with self.mock(handler):result=await llm.test_connection(p)
  self.assertEqual(result['thinking']['reasoningTokens'],12);self.assertEqual(result['thinking']['probe']['status'],'rejected')
  self.assertEqual(calls[1]['generationConfig']['thinkingConfig']['thinkingLevel'],'__invalid_probe__')
