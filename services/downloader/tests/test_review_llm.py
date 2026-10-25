"""Transport failure classification and safe retry; no external model calls."""
import asyncio,json,ssl,sys,unittest,time,threading,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx,review_llm as llm

class Stream(httpx.AsyncByteStream):
 def __init__(self,error=None):self.error=error
 async def __aiter__(self):
  yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
  if self.error:raise self.error
  yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'

class ConnectionTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.profile={'model':'fixture','apiKey':'private-fixture-secret','endpoint':'https://fixture.invalid/v1/chat/completions','timeout':10}
  self.real_client=httpx.AsyncClient
  proxy=patch.object(llm,'system_proxy',return_value=None);proxy.start();self.addCleanup(proxy.stop)
 def client(self,handler):
  return patch.object(llm.httpx,'AsyncClient',side_effect=lambda **kw:self.real_client(transport=httpx.MockTransport(handler),**kw))
 async def test_preconnection_failure_retries_once(self):
  attempts=[];updates=[]
  async def handler(req):
   attempts.append(req)
   if len(attempts)==1:raise httpx.ConnectError('temporary connection failure')
   return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=Stream())
  with self.client(handler):result=await llm.chat(self.profile,[],lambda:False,progress=lambda **kw:updates.append(kw))
  self.assertEqual(result,'hello');self.assertEqual(len(attempts),2);self.assertTrue(any(v.get('connectionStatus')=='retrying' for v in updates))
 async def test_permanent_failure_reports_safe_details(self):
  calls=[]
  async def handler(req):calls.append(req);raise httpx.ConnectError('private-fixture-secret https://user:secret@host/?key=secret')
  with self.client(handler),self.assertRaises(llm.ConnectionFailure) as caught:await llm.chat(self.profile,[],lambda:False)
  error=caught.exception;self.assertEqual(len(calls),2);self.assertEqual(error.diagnostics['type'],'ConnectError');self.assertEqual(error.diagnostics['phase'],'connecting');self.assertIn('尚未收到',str(error));self.assertNotIn('secret',str(error)+json.dumps(error.diagnostics))
  self.assertEqual(error.diagnostics['networkMode'],'direct')
 async def test_failure_records_direct_route(self):
  async def handler(req):raise httpx.ConnectError('offline')
  with self.client(handler),self.assertRaises(llm.ConnectionFailure) as caught:
   await llm.chat({**self.profile,'networkMode':'direct'},[],lambda:False)
  self.assertEqual(caught.exception.diagnostics['networkMode'],'direct');self.assertIn('直连 API',str(caught.exception))
 async def test_loopback_stays_direct_even_with_proxy_environment(self):
  hits=[]
  class Target(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    self.rfile.read(int(self.headers['Content-Length']));hits.append('target')
    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
    self.wfile.write(b'{"choices":[{"message":{"content":"connection OK"},"finish_reason":"stop"}]}')
  class Proxy(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    self.rfile.read(int(self.headers['Content-Length']));hits.append('proxy');self.send_response(502);self.end_headers()
  target=ThreadingHTTPServer(('127.0.0.1',0),Target);proxy=ThreadingHTTPServer(('127.0.0.1',0),Proxy)
  for server in (target,proxy):threading.Thread(target=server.serve_forever,daemon=True).start()
  proxy_url=f'http://127.0.0.1:{proxy.server_port}'
  env={k:proxy_url for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')};env.update(NO_PROXY='',no_proxy='')
  profile={**self.profile,'baseUrl':f'http://127.0.0.1:{target.server_port}'}
  try:
   with patch.dict(os.environ,env):
    result=await llm.test_connection(profile)
    self.assertEqual(result['reply'],'connection OK');self.assertEqual(result['networkMode'],'direct');self.assertEqual(hits,['target'])
    result=await llm.test_connection({**profile,'networkMode':'system'})
    self.assertEqual(result['reply'],'connection OK');self.assertEqual(hits,['target','target'])
    import embedding_limits
    response=await asyncio.to_thread(embedding_limits.post,profile['baseUrl']+'/embeddings',{}, {'input':['text']},10,lambda:None)
    self.assertEqual(response.status_code,200);self.assertEqual(hits,['target','target','target'])
  finally:
   for server in (target,proxy):await asyncio.to_thread(server.shutdown);server.server_close()
 async def test_partial_stream_is_never_replayed(self):
  calls=[]
  async def handler(req):calls.append(req);return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=Stream(httpx.ReadError('broken')))
  with self.client(handler),self.assertRaises(llm.ConnectionFailure) as caught:await llm.chat(self.profile,[],lambda:False)
  self.assertEqual(len(calls),1);self.assertEqual(caught.exception.diagnostics['received'],5);self.assertEqual(caught.exception.diagnostics['phase'],'streaming')
 async def test_certificate_failure_is_not_retried(self):
  calls=[]
  async def handler(req):
   calls.append(req)
   try:raise ssl.SSLCertVerificationError('certificate invalid')
   except ssl.SSLError as cause:raise httpx.ConnectError('TLS') from cause
  with self.client(handler),self.assertRaises(llm.ConnectionFailure) as caught:await llm.chat(self.profile,[],lambda:False)
  self.assertEqual(len(calls),1);self.assertEqual(caught.exception.diagnostics['kind'],'TLS')
 async def test_cancel_during_backoff_stops_retry(self):
  calls=[];updates=[]
  async def handler(req):calls.append(req);raise httpx.ConnectError('temporary')
  with self.client(handler),self.assertRaises(llm.Cancelled):await llm.chat(self.profile,[],lambda:bool(updates),progress=lambda **kw:updates.append(kw))
  self.assertEqual(len(calls),1)
 async def test_probe_requires_completed_content(self):
  async def handler(req):return httpx.Response(200,headers={'Content-Type':'application/json'},json={'choices':[{'message':{'reasoning_content':'Only reasoning'}}]})
  with self.client(handler),self.assertRaisesRegex(ValueError,'没有返回正文'):await llm.test_connection({**self.profile,'baseUrl':'https://fixture.invalid'})
 async def test_long_content_and_reasoning_have_no_application_output_cap(self):
  content='x'*2_000_001;thought='y'*2_000_001;requests=[];received=[]
  async def handler(req):
   requests.append(json.loads(req.content))
   return httpx.Response(200,headers={'Content-Type':'application/json'},json={'choices':[{'message':{'content':content,'reasoning_content':thought},'finish_reason':'stop'}]})
  with self.client(handler):result=await llm.chat(self.profile,[],lambda:False,on_reasoning=lambda value:received.append(len(value)))
  self.assertEqual(result,content);self.assertEqual(received,[len(thought)])
  self.assertFalse({'max_tokens','max_completion_tokens','max_output_tokens'} & set(requests[0]))
 async def test_reasoning_is_streamed_separately_for_supported_fields(self):
  chunks=[{'reasoning_content':'先查'}, {'reasoning':'资料。'}, {'reasoning_details':[{'type':'reasoning.text','text':'再核对。'},{'type':'reasoning.encrypted','data':'opaque'}]}, {'content':'Answer'}]
  class Thoughts(httpx.AsyncByteStream):
   async def __aiter__(self):
    for delta in chunks:yield ('data: '+json.dumps({'choices':[{'delta':delta}]})+'\n\n').encode()
    yield b'data: [DONE]\n\n'
  async def handler(req):return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=Thoughts())
  thoughts=[];content=[];progress=[]
  with self.client(handler):result=await llm.chat(self.profile,[],lambda:False,on_text=content.append,on_reasoning=thoughts.append,progress=lambda **v:progress.append(v))
  self.assertEqual(thoughts,['先查','先查资料。','先查资料。再核对。']);self.assertEqual(result,'Answer');self.assertEqual(content[-1],'Answer');self.assertNotIn('先查',result)
  self.assertEqual(progress[-1],{'received':6,'reasoningCharacters':len(thoughts[-1])})
 async def test_reasoning_keeps_real_connection_alive_past_timeout(self):
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    self.rfile.read(int(self.headers['Content-Length']));self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
    for _ in range(4):
     self.wfile.write(b'data: {"choices":[{"delta":{"reasoning_content":"checking "}}]}\n\n');self.wfile.flush();time.sleep(3)
    self.wfile.write(b'data: {"choices":[{"delta":{"content":"done"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();thoughts=[]
  try:
   start=time.monotonic();result=await llm.chat({**self.profile,'endpoint':f'http://127.0.0.1:{server.server_port}/v1/chat/completions'},[],lambda:False,on_reasoning=thoughts.append)
   self.assertGreater(time.monotonic()-start,10);self.assertEqual(result,'done');self.assertEqual(len(thoughts),4)
  finally:await asyncio.to_thread(server.shutdown);server.server_close();thread.join()
 def test_full_endpoint_normalization_and_reject_secrets(self):
  for base in ['https://fixture.invalid','https://fixture.invalid/v1','https://fixture.invalid/v1/chat/completions/','https://fixture.invalid/v1/models']:
   self.assertEqual(llm.endpoint(base),'https://fixture.invalid/v1/chat/completions')
  with self.assertRaises(ValueError):llm.endpoint('https://user:secret@fixture.invalid?key=secret')

if __name__=='__main__':unittest.main()
