"""Actual Rust search requests; local SSE only, no real research data or models."""
import json,os,subprocess,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
requests=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  text='### Broad search\n```pubmed\nnephropathy[tiab]\n```'
  data={'choices':[{'delta':{'content':text}}]}
  self.wfile.write(('data: '+json.dumps(data)+'\n\ndata: [DONE]\n\n').encode())
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with tempfile.TemporaryDirectory(prefix='language-search-',dir=ROOT/'tmp') as folder:
  env={**os.environ,'SCHOLARNOTELM_ROOT':folder}
  def rpc(action,**args):
   p=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':args}),text=True,capture_output=True,check=True,env=env)
   result=json.loads(p.stdout);assert result['ok'],result;return result['data']
  profile=rpc('profile.save',profile={'name':'Local fixture','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','models':['fixture'],'apiKey':'','timeout':10})
  t=rpc('chat.new',project='test',contentLanguage='en')
  rpc('chat',project='test',chatId=t['id'],message='Design a search',profileId=profile['id'])
  assert 'explain searches in English' in requests[-1]['messages'][0]['content']
  stored=rpc('chat.get',project='test',id=t['id'])
  assert stored['messages'][-1]['contentLanguage']=='en'
  assert 'nephropathy[tiab]' in stored['messages'][-1]['text']
  rpc('chat.language',project='test',id=t['id'],contentLanguage='zh')
  fork=rpc('chat.fork',project='test',id=t['id'],keepCount=len(stored['messages']))
  assert fork['contentLanguage']=='en'
  rpc('chat',project='test',chatId=t['id'],message='继续',profileId=profile['id'])
  assert '默认用中文' in requests[-1]['messages'][0]['content']
  assert rpc('chat.get',project='test',id=t['id'])['messages'][-1]['contentLanguage']=='zh'
  print(json.dumps({'passed':True,'requests':len(requests),'checks':['English/Chinese search prompt','stored turn language','branch-point language','PubMed query preserved']},ensure_ascii=False))
finally:server.shutdown();server.server_close()
