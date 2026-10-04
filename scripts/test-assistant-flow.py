"""Streaming, reasoning, branch/cancel/error persistence; uses a local mock only."""
import json,os,pathlib,shutil,subprocess,tempfile,threading,time,sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=pathlib.Path(__file__).resolve().parents[1];TEST=pathlib.Path(tempfile.mkdtemp(prefix='assistant-stream-',dir=ROOT/'tmp'))
(TEST/'runtimes').mkdir(exist_ok=True);(TEST/'runtimes/downloader').symlink_to(ROOT/'runtimes/downloader',target_is_directory=True);(TEST/'services').symlink_to(ROOT/'services',target_is_directory=True)
ENV=dict(os.environ,SCHOLARNOTELM_ROOT=str(TEST));BIN=str(ROOT/'cache/tauri-target/debug/research-cli');requests=[];checks=[]
def rpc(action,**args):
 p=subprocess.run([BIN],input=json.dumps(dict(action=action,args=args)),text=True,capture_output=True,env=ENV,check=True);v=json.loads(p.stdout)
 if not v['ok']:raise RuntimeError(v['error'])
 return v['data']
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  b=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(b)
  assert b['stream'] and 'max_tokens' not in b and 'max_completion_tokens' not in b
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  def event(delta=None,finish=None):
   payload=json.dumps({'choices':[{'delta':delta or {},'finish_reason':finish}]},ensure_ascii=False)
   data=('data: '+payload+'\r\n\r\n').encode();mid=len(data)//2;self.wfile.write(data[:mid]);self.wfile.flush();self.wfile.write(data[mid:]);self.wfile.flush()
  try:
   event({'reasoning_content':'先确定研究对象。'})
   if b['model']=='reasoning-only':event(finish='stop');return
   if b['model']=='slow':
    for i in range(4):time.sleep(3);event({'reasoning_content':f'核验概念 {i}。'})
   if b['model']=='cancel':time.sleep(4)
   if b['model']=='burst':
    for i in range(200):event({'content':f'片段{i}。'})
    time.sleep(.12);event(finish='stop');self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush();return
   event({'content':'### 小胶质细胞基础检索\n\n设计如下：\n\n```pubmed\n'})
   if b['model']=='broken':return
   event({'content':'"Microglia"[MeSH Terms] OR microglia*[tiab]\n```\n'})
   event(finish='stop');self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
def profile(model):return rpc('profile.save',profile=dict(id='fixture',name='Fixture',baseUrl=f'http://127.0.0.1:{server.server_port}',model=model,temperature=None,timeout=10,maxTokens=1,tokenField='max_completion_tokens'))
def streamed(chat,mode='normal',cancel=False,save_query=False):
 profile(mode);start=time.monotonic();sid='test-'+str(time.time_ns());p=subprocess.Popen([BIN,'--stream'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=ENV);p.stdin.write(json.dumps({'action':'chat','args':{'project':'test','chatId':chat['id'],'message':'设计小胶质细胞检索','streamId':sid}}));p.stdin.close();events=[];first=None
 for line in p.stdout:
  e=json.loads(line);events.append(e)
  if e['type']=='update' and first is None:
   first=time.monotonic()-start
   if save_query:
    began=time.monotonic();saved=rpc('query.save',project='test',name='生成中保存检索式',text='kidney[tiab]');assert saved['queries'] and p.poll() is None;print('Concurrent query save seconds:',round(time.monotonic()-began,3))
   if cancel:rpc('chat.cancel',streamId=sid)
 p.wait(timeout=20);assert p.returncode==0;assert events[-1]['ok'],events[-1]
 assert first is not None and first<3
 return events[-1]['data'],events,time.monotonic()-start
try:
 rpc('workspace',project='test');profile('normal')
 # Reuse the established MeSH index without modifying it.
 c=sqlite3.connect(ROOT/'data/research/research.sqlite3');row=c.execute("SELECT value FROM settings WHERE key='mesh'").fetchone();c.close()
 if row:
  (TEST/'data/reference').mkdir(parents=True,exist_ok=True);(TEST/'data/reference/mesh').symlink_to(ROOT/'data/reference/mesh',target_is_directory=True)
  c=sqlite3.connect(TEST/'data/research/research.sqlite3');c.execute("INSERT INTO settings VALUES('mesh',?)",row);c.commit();c.close()
 t=rpc('chat.new',project='test');history,events,seconds=streamed(t)
 assert history[-1]['result']['modelLabel']=='Fixture/normal'
 assert len(history)==2 and history[-1]['reasoning'] and not history[-1]['error'];q=history[-1]['result']['queries'][0];assert 'probe' not in q
 if row:assert q['meshCheck'][0]['verified']
 assert any(e.get('reasoning') and not e.get('text') for e in events)
 assert not rpc('workspace',project='test')['corpus']['papers']
 assert not list((TEST/'data/research').glob('*ncbi*'))
 checks.append('True SSE updates before completion; reasoning; canonical MeSH verification; no PubMed probing or token caps')
 fork=rpc('chat.fork',project='test',id=t['id'],keepCount=1);assert len(fork['messages'])==1 and fork['parentId']==t['id'];assert len(rpc('chat.get',project='test',id=t['id'])['messages'])==2
 edited=rpc('chat.fork',project='test',id=t['id'],keepCount=0);assert edited['messages']==[];streamed(edited)
 assert len(rpc('chat.get',project='test',id=t['id'])['messages'])==2
 rpc('chat.rename',project='test',id=fork['id'],name='分支 A');assert rpc('chat.get',project='test',id=fork['id'])['name']=='分支 A'
 checks.append('Independent conversations, branch snapshots, edited/regenerated branches preserve originals')
 profile('reasoning-only')
 try:rpc('llm.test')
 except RuntimeError as exc:assert '没有返回正文' in str(exc)
 else:raise AssertionError('Connection test must require a usable completed answer')
 t2=rpc('chat.new',project='test');h,_,_=streamed(t2,'reasoning-only');assert h[-1]['reasoning'] and not h[-1]['error']
 checks.append('Connection test rejects reasoning-only output; chat still preserves received reasoning')
 t3=rpc('chat.new',project='test');h,_,elapsed=streamed(t3,'slow');assert elapsed>10 and not h[-1]['error']
 checks.append('12-second reasoning stream survives configured 10-second idle timeout')
 t4=rpc('chat.new',project='test');h,_,elapsed=streamed(t4,'cancel',True);assert elapsed<3 and h[-1]['cancelled'] and h[-1]['reasoning'];streamed(t4)
 checks.append('Cancellation promptly releases chat lock; partial reasoning preserved; immediate resend works')
 t5=rpc('chat.new',project='test');h,_,_=streamed(t5,'broken');assert h[-1]['error'] and h[-1]['text'] and h[-1]['reasoning']
 checks.append('Truncated stream persists partial answer and exposes recoverable error')
 t6=rpc('chat.new',project='test');h,events,_=streamed(t6,'burst');expected=''.join(f'片段{i}。' for i in range(200));updates=[e for e in events if e['type']=='update'];assert h[-1]['text']==expected and updates[-1]['text']==expected;assert 2<=len(updates)<80;assert all(isinstance(e.get('emittedAt'),int) for e in updates)
 checks.append('200 rapid SSE deltas coalesced; final text and final update exact; transport timestamps included')
 t7=rpc('chat.new',project='test');streamed(t7,'cancel',save_query=True)
 checks.append('Query saved while stream is still running; no chat-wide database lock')
 report=dict(passed=True,checks=checks,requests=len(requests),model='Local controlled SSE fixture; no user credentials used')
 (ROOT/'docs/ASSISTANT_TEST_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
finally:server.shutdown();shutil.rmtree(TEST)
