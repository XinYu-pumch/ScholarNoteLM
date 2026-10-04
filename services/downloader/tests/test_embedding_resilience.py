"""Exercise the real HTTP transport and quota ledger without paid API calls."""
import json, socket, sys, tempfile, threading, time, unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import adaptive_embedding as adaptive
import embedding_controller as control
import embedding_limits as limits
import vector_service as v

class ResilienceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.e=SimpleNamespace(ROOT=self.root)
  self.actions=[];self.requests=[];self.guard=threading.Lock()
  owner=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
    with owner.guard:
     action=owner.actions.pop(0) if owner.actions else 'ok'
     owner.requests.append((time.time(),len(payload['input']),action))
    if action=='disconnect':
     self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
    if action=='timeout':time.sleep(.25)
    if action=='slow':time.sleep(.04)
    code=action if isinstance(action,int) else 200
    body={'usage':{'prompt_tokens':10*len(payload['input'])},'data':[{'index':i,'embedding':[1.,float(int(t)+1)]} for i,t in enumerate(payload['input'])]} if code==200 else {'error':'fixture'}
    if action=='malformed':body['data']=[]
    raw=json.dumps(body).encode()
    try:
     self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
     if code==429:self.send_header('Retry-After','.01')
     self.end_headers();self.wfile.write(raw)
    except (BrokenPipeError,ConnectionResetError):pass
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.cfg={**v.DEFAULTS,'baseUrl':f'http://127.0.0.1:{self.server.server_port}/v1','model':'fixture','apiKey':'secret-fixture','rpm':1800,'tpm':450000,'timeout':.1}
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
 def run_inputs(self,n=12,check=lambda:None):
  saved={};updates=[]
  def save(group,values):
   for (ident,text),vector in zip(group,values):
    self.assertNotIn(ident,saved);self.assertEqual(vector,[1.,float(int(text)+1)]);saved[ident]=vector
  adaptive.run_inputs(self.e,self.cfg,[(str(i),str(i)) for i in range(n)],check,updates.append,self.root,save)
  return saved,updates
 def test_disconnect_timeout_503_429_slow_then_restore_every_chunk(self):
  self.actions=['disconnect','timeout',503,429,'slow']
  with patch.object(control,'RETRY_BASE_SECONDS',.02),patch.object(control,'RETRY_CAP_SECONDS',.04):
   saved,updates=self.run_inputs()
  self.assertEqual(set(saved),{str(i) for i in range(12)})
  self.assertEqual(updates[-1]['completed'],12);self.assertEqual(updates[-1]['retries'],4)
  self.assertTrue(any(u['state'].startswith('waiting_') for u in updates))
  events=[json.loads(line) for line in (self.root/'embedding-requests.jsonl').read_text().splitlines()]
  self.assertEqual(len(events),len(self.requests))
  self.assertEqual({e.get('errorKind') for e in events if e['status']==0},{'timeout','network'})
  self.assertNotIn('secret-fixture',(self.root/'embedding-requests.jsonl').read_text())
  # Count failed/unknown-usage requests at their full reservation, not zero.
  for at,_,_ in self.requests:
   window=[e for e in events if at-60<e['at']<=at]
   self.assertLessEqual(len(window),1800)
   self.assertLessEqual(sum(e['reserved'] for e in window),450000)
  limiter=limits.Limiter(self.root,self.cfg)
  with limiter.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],len(events))
 def test_user_stop_interrupts_network_wait(self):
  self.actions=[503]*10;started=time.monotonic()
  def check():
   if time.monotonic()-started>.2:raise InterruptedError('用户停止')
  with self.assertRaises(InterruptedError):self.run_inputs(check=check)
  self.assertLess(time.monotonic()-started,1)
  self.assertEqual(len(self.requests),1)
 def test_auth_and_bad_vectors_fail_without_retry(self):
  for failure in (401,'malformed'):
   with self.subTest(failure=failure):
    self.actions=[failure];before=len(self.requests)
    with self.assertRaises(ValueError):self.run_inputs()
    self.assertEqual(len(self.requests),before+1)
 def test_controller_reverts_when_latency_rises_without_gain(self):
  now=[0.];c=control.Controller(self.cfg,clock=lambda:now[0])
  c.target=4;c.baseline=(1.,100.);c.samples=[(2.,250)]*3;now[0]=10
  c.success(2.,250)
  self.assertEqual(c.target,3);self.assertEqual(c.batch,16)
 def test_recovery_needs_three_successes_and_has_bounds(self):
  now=[0.];c=control.Controller(self.cfg,clock=lambda:now[0])
  c.failed(limits.TransientError('offline',kind='network'))
  self.assertEqual(c.target,1);self.assertEqual(c.state(),'waiting_network')
  now[0]=c.retry_at+.01
  for _ in range(2):c.success(.1,10);self.assertTrue(c.recovering)
  c.success(.1,10);self.assertFalse(c.recovering)
  for _ in range(200):now[0]+=11;c.success(100.,10)
  self.assertLessEqual(c.target,16);self.assertLessEqual(c.batch,32)
 def test_changed_model_falls_back_to_conservative(self):
  self.assertFalse(adaptive.verified_tokenizer(self.e,self.cfg))
  with patch.object(v,'embed',return_value=[[1.,2.]]) as embed:
   updates=[];adaptive.run_inputs(self.e,self.cfg,[('one','1')],lambda:None,updates.append,self.root,lambda *_:None,'auto')
  self.assertEqual(embed.call_args.kwargs['reserved_tokens'],8192)
  self.assertEqual(updates[-1]['tokenBudget'],'conservative')

if __name__=='__main__':unittest.main()
