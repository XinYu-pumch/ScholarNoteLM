"""Exercise connection verification against an actual localhost HTTP endpoint."""
import json,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,vector_service as v

class EmbeddingConnectionTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT=Path(self.tmp.name)
  self.requests=[];self.status=200;self.body={'data':[{'index':0,'embedding':[0.1,0.2,0.3]}]};test=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    test.requests.append({'path':self.path,'body':json.loads(self.rfile.read(int(self.headers['Content-Length']))),'authorization':self.headers.get('Authorization')})
    self.send_response(test.status);self.end_headers();self.wfile.write((test.body if isinstance(test.body,str) else json.dumps(test.body)).encode())
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
  self.args={'baseUrl':f'http://127.0.0.1:{self.server.server_port}/v1','model':'draft-model','apiKey':'test-secret','testText':'  Test immune regulation.  '}
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();e.ROOT=self.old;self.tmp.cleanup()
 def test_real_request_uses_unsaved_fields_without_persisting_or_indexing(self):
  out=v.rpc(e,'test',self.args)
  self.assertEqual(out['dimension'],3);self.assertEqual(out['model'],'draft-model');self.assertEqual(out['vectors'],1)
  self.assertEqual(out['endpoint'],self.args['baseUrl']+'/embeddings');self.assertGreaterEqual(out['seconds'],0)
  self.assertEqual(self.requests[0]['body']['input'],['Test immune regulation.']);self.assertEqual(self.requests[0]['path'],'/v1/embeddings')
  self.assertEqual(self.requests[0]['authorization'],'Bearer test-secret');self.assertNotIn('test-secret',json.dumps(out))
  self.assertFalse((e.ROOT/'config/embedding.json').exists());self.assertFalse((e.ROOT/'workspace').exists())
 def test_complete_endpoint_does_not_duplicate_suffix(self):
  v.rpc(e,'test',{**self.args,'baseUrl':self.args['baseUrl']+'/embeddings/'})
  self.assertEqual(self.requests[0]['path'],'/v1/embeddings')
 def test_saved_key_reused_but_draft_model_not_saved(self):
  v.rpc(e,'settings.save',{**self.args,'model':'saved-model'})
  before=(e.ROOT/'config/embedding.json').read_bytes()
  v.rpc(e,'test',{**self.args,'apiKey':''})
  self.assertEqual(self.requests[0]['authorization'],'Bearer test-secret');self.assertEqual(before,(e.ROOT/'config/embedding.json').read_bytes())
 def test_success_http_with_invalid_vector_is_not_success(self):
  for body in ('<html>not an API</html>',[],{'data':[]},{'data':[None]},{'data':[{'index':0,'embedding':[]}]},{'data':[{'index':0,'embedding':[0,0]}]},{'data':[{'index':0,'embedding':[float('nan')]}]},{'data':[{'embedding':[1,2]}]}):
   with self.subTest(body=str(body)):
    self.body=body
    with self.assertRaises(ValueError):v.rpc(e,'test',self.args)
 def test_failure_is_one_request_with_specific_redacted_error(self):
  for status,reason in ((401,'API Key'),(404,'接口或模型'),(429,'限流'),(503,'服务端异常')):
   self.status=status;self.body={'error':'upstream echo test-secret'};self.requests.clear()
   with self.assertRaisesRegex(ValueError,reason) as caught:v.rpc(e,'test',self.args)
   self.assertNotIn('test-secret',str(caught.exception));self.assertEqual(len(self.requests),1)
 def test_invalid_text_never_sends_request(self):
  for text in (' ',None,'x'*1001):
   with self.assertRaisesRegex(ValueError,'测试文本'):v.rpc(e,'test',{**self.args,'testText':text})
  self.assertEqual(self.requests,[])

if __name__=='__main__':unittest.main()
