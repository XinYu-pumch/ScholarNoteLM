"""Real desktop RPC, worker and offline models; isolated papers and local LLM fixture."""
import gzip,json,os,sqlite3,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e,storage,review_service as r,vector_service as v,retrieval_settings as rs
TEST_LANGUAGE=os.environ.get('TEST_CONTENT_LANGUAGE')
import provider_fixture as pf
requests=[];bad_unit=None;slow=False;started=threading.Event();concurrent=0;peak=0;mutex=threading.Lock()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  global concurrent,peak
  value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(value);pf.capture(self.headers,value)
  if 'input' in value:
   self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
   self.wfile.write(json.dumps({'data':[{'index':i,'embedding':[1.0,len(t)%7+.1,len(t)%3+.1]} for i,t in enumerate(value['input'])],'usage':{'prompt_tokens':sum(len(t)//3 for t in value['input'])}}).encode());return
  with mutex:concurrent+=1;peak=max(peak,concurrent)
  try:
   started.set()
   if slow:time.sleep(5)
   self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
   def send(v):self.wfile.write(('data: '+json.dumps(v,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
   send({'choices':[{'delta':{'reasoning_content':'检查证据与层级'}}]});time.sleep(.3)
   payload=json.loads(value['messages'][-1]['content']);output=payload['outputContract']
   roles={n['node_id']:n['role'] for n in payload['unit']['nodes']}
   for index,n in enumerate(output['sections'],1):
    n['blocks'][0]['text']='根据提供材料，肠道菌群与黏膜免疫有关。 [E1]' if roles[n['node_id']]=='leaf' and payload['evidencePool'] else '本节组织下述机制与证据。'
    if roles[n['node_id']]=='leaf' and payload['evidencePool']:
     tid='T'+str(index);n['blocks'][0]['text']+=' 见 {{ref:'+tid+'}}。'
     n['blocks'].append({'type':'table','table_id':tid,'title':'证据摘要','columns':['观察','来源'],'rows':[['材料概述','[E1]']],'notes':'仅作材料展示。'})
   text='invalid JSON fixture' if output.get('unit_id')==bad_unit else json.dumps(output,ensure_ascii=False)
   for part in (text[:35],text[35:]):send({'choices':[{'delta':{'content':part}}]})
   send({'choices':[{'delta':{},'finish_reason':'stop'}]});self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError):pass
  finally:
   with mutex:concurrent-=1
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with tempfile.TemporaryDirectory(prefix='review-writing-e2e-',dir=ROOT/'tmp') as temp:
  app=Path(temp);(app/'runtimes').mkdir();(app/'tmp').mkdir()
  for runtime in ('downloader','retrieval'):(app/'runtimes'/runtime).symlink_to(ROOT/'runtimes'/runtime,target_is_directory=True)
  (app/'services').symlink_to(ROOT/'services',target_is_directory=True);(app/'models').symlink_to(ROOT/'models',target_is_directory=True)
  pf.setup(app,ROOT,f'http://127.0.0.1:{server.server_port}/v1',['fixture'])
  e.ROOT,e.PROJECT=app,'test';base=storage.project_dir(app,'test')
  text='The gut microbiota regulates mucosal immune responses through short chain fatty acids, intestinal barrier function and regulatory T cells. These mechanisms are supported by experimental evidence, but effects depend on host context.'
  articles=''.join(f'<PubmedArticle><MedlineCitation><PMID>{123+i}</PMID><Article><ArticleTitle>Microbiota study {i}</ArticleTitle><Abstract><AbstractText>{text} Variant {i}.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for i in range(9))
  e.atomic(base/'pubmed/current.xml','<PubmedArticleSet>'+articles+'</PubmedArticleSet>')
  cfg=app/'data/research/research.sqlite3';cfg.parent.mkdir(parents=True)
  with sqlite3.connect(cfg) as c:
   c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
   c.executemany('INSERT INTO settings VALUES(?,?)',[('profiles',json.dumps([pf.profile({'id':'fixture','model':'fixture','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','apiKey':'isolated-test-secret','sendTemperature':False,'timeout':10})])),('activeProfile',json.dumps('fixture'))])
  def rpc(op,**args):
   process=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':'review.'+op,'args':{'project':'test','name':'ReviewTest',**args}}),text=True,capture_output=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(app)},timeout=30)
   value=json.loads(process.stdout)
   if not value['ok']:raise AssertionError(value.get('error'))
   return value['data']
  def wait():
   end=time.monotonic()+180;last=''
   while time.monotonic()<end:
    d=rpc('writing.status');phase=d['job'].get('phase','')
    if phase!=last:print(phase,flush=True);last=phase
    if d['job']['state'] not in ('queued','running','stopping'):return d
    time.sleep(.2)
   raise AssertionError('worker timeout')
  rpc('create',**({'contentLanguage':TEST_LANGUAGE} if TEST_LANGUAGE else {}),topic='肠道菌群综述')
  rpc('import',revision=0,csv='Serial,Title\n1,免疫机制\n1.1,菌群调节\n1.1.1,短链脂肪酸\n1.1.2,调节性T细胞\n1.2,屏障功能\n2,研究方向\n')
  v.rpc(e,'settings.save',{'baseUrl':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture-embedding','apiKey':'isolated-test-secret','autoIndex':False,'rpm':600,'tpm':120000})
  v.rpc(e,'test',{})
  tick=time.monotonic();d=rpc('writing.prepare');d=wait()
  assert d['job']['state']=='done',d['job']
  assert d['prepared']==d['total']==3,d
  assert not any('messages' in req for req in requests),'Preparation called a writing LLM'
  query_inputs=[req['input'][0] for req in requests if len(req.get('input',[]))==1]
  assert all(q in query_inputs for q in ('短链脂肪酸','调节性T细胞','屏障功能','研究方向')),query_inputs
  prompt_files=list((base/'review/ReviewTest/review_parts').glob('prompt_section_*.json'));assert len(prompt_files)==3
  before_embeddings=len(requests);d=rpc('writing.start');d=wait()
  if pf.ENABLED:assert len(set(pf.sessions()))==3,'Concurrent units share a session'
  assert all('messages' in req for req in requests[before_embeddings:]),'Writing repeated recall'
  sent=[req['messages'] for req in requests[before_embeddings:]]
  if TEST_LANGUAGE=='en':assert all('Write in English' in messages[0]['content'] for messages in sent)
  import review_bundle
  for prompt_file in prompt_files:
   package=json.loads(prompt_file.read_text())
   assert review_bundle.messages(package,prompt_file.parent,{'model':'fixture'}) in sent
  assert len(list((base/'review/ReviewTest/review_parts').glob('section_*.json')))==3
  if d['job']['state']!='done':
   for log in (base/'review/ReviewTest/logs').glob('*/worker.log'):print(log.read_text()[-4000:])
  assert d['job']['state']=='done',d['job'];assert d['latest']==d['total']==3,d
  path=base/'review/ReviewTest';sections=list((path/'sections').glob('*.json'));assert len(sections)==3
  for f in sections:
   saved=json.loads(f.read_text());assert saved['evidence'];assert all(len(v['chunks'])==7 for v in saved['evidence'].values())
  archives=list((path/'logs').glob('*/*.gz'));assert archives
  log_storage={'originalBytes':sum(len(gzip.decompress(f.read_bytes())) for f in archives),'storedBytes':sum(f.stat().st_size for f in archives)}
  assert log_storage['storedBytes']<log_storage['originalBytes']
  assert not list((path/'logs').glob('*/input.json'))
  assert all(json.loads(gzip.decompress(f.read_bytes())) in [r['messages'] for r in requests if 'messages' in r] for f in (path/'logs').glob('*/*.prompt.json.gz'))
  assert 'max_tokens' not in requests[-1] and 'temperature' not in requests[-1]
  n=len(requests);rpc('writing.start');assert len(requests)==n;assert rpc('writing.status')['job']['state']=='done'
  exported={fmt:Path(rpc('writing.export',format=fmt)['path']) for fmt in ('md','html','docx')}
  assert all(p.is_file() for p in exported.values())
  from bs4 import BeautifulSoup
  html=BeautifulSoup(exported['html'].read_text(),'html.parser')
  if TEST_LANGUAGE=='en':
   assert html.html['lang']=='en'
   assert html.find(id='toggle-ref').get_text()=='Citation details'
  assert len(html.select('.body-table'))==4
  assert len({figure['id'] for figure in html.select('.body-table')})==4
  for link in html.select('.content a[href^="#obj_"]'):assert html.find(id=link['href'][1:]) is not None
  assert '{{ref:' not in exported['md'].read_text()
  # Public deletion is observed even while idle; failed JSON is retryable through real RPC.
  target=d['units'][0];public=path/'review_parts'/f'section_{target["serial"]}.json';public.unlink()
  assert rpc('writing.status')['latest']==2
  assert rpc('writing.section',nodeId=target['leafIds'][0]).get('sections',[])==[]
  bad_unit=target['serial'];n=len(requests);rpc('writing.start');failed=wait()
  assert failed['job']['state']=='partial' and failed['job']['failed']==1 and failed['job']['pending']==0,failed['job']
  assert len(requests)==n+2
  saved_result=json.loads((path/'logs'/failed['job']['token']/'result.json').read_text())
  assert 'JSON' in saved_result['items'][target['id']]['error']
  bad_unit=None;n=len(requests);rpc('writing.retry');d=wait()
  assert d['latest']==3 and d['job']['total']==1 and d['job']['completed']==1
  assert len(requests)==n+1 and saved_result['failed']==1
  if pf.ENABLED:assert len(set(pf.sessions()[-3:]))==1,'Repair/retry changed session'
  prompt_files[0].unlink();assert rpc('writing.status')['prepared']==2
  rpc('writing.prepare.resume');d=wait();assert d['prepared']==3 and d['latest']==3
  before={p.name:p.read_bytes() for p in sections}
  slow=True;started.clear();rpc('writing.start',unitIds=[d['units'][0]['id']]);assert started.wait(15)
  tick_cancel=time.monotonic();rpc('writing.cancel');cancelled=wait();assert cancelled['job']['state']=='cancelled',cancelled
  assert time.monotonic()-tick_cancel<3
  assert all((path/'sections'/name).read_bytes()==content for name,content in before.items())
  # A fresh preparation always archives then clears; resume above deliberately did not.
  archived=rpc('writing.manuscripts');assert archived and any(not a['partial'] for a in archived)
  preserved={str(p):p.read_bytes() for p in exported.values()}
  slow=False;rpc('writing.prepare',confirm=True);d=wait()
  assert d['prepared']==3 and d['latest']==0 and not d['hasContent'],d
  assert not list((path/'sections').glob('*.json'))
  assert all(Path(p).read_bytes()==content for p,content in preserved.items())
  copied=rpc('create',name='CopyReview',outlineSource='workspace',sourceWorkspace='ReviewTest')
  assert len(copied['rows'])==6 and copied['workspace']['outlineSource']['workspace']=='ReviewTest'
  assert not (base/'review/CopyReview/sections').exists()
  rpc('writing.start');d=wait();assert d['latest']==3
  rpc('writing.reset',confirm=True);assert not rpc('writing.status')['hasContent']
  for fmt in ('md','html','docx'):
   historical=rpc('writing.manuscript.export',id=archived[0]['id'],format=fmt);assert Path(historical['path']).is_file()
  assert all(Path(p).read_bytes()==content for p,content in preserved.items())
  for f in path.rglob('*'):
   if f.suffix in ('.txt','.json','.log','.csv','.md'):assert 'isolated-test-secret' not in f.read_text(errors='replace')
   if f.suffix=='.gz':assert b'isolated-test-secret' not in gzip.decompress(f.read_bytes())
  pf.verify()
  print(json.dumps({'success':True,'auditStorage':log_storage,'seconds':round(time.monotonic()-tick,2),'requests':len(requests),'writingUnits':3,'leafQueries':4,'topK':7,'peakHttpConcurrency':peak,'checks':['real Rust RPC','real independent worker','verified API recall, default no reranking','Chinese queries unchanged','two-stage prompt files sent exactly','writing does not recall again','abstract fallback','mixed-depth complete assembly','all latest skips generation','external section and prompt deletion','JSON failure result archived','retry sends failed item only','exports md/html/docx','cancel active HTTP within 3 seconds','completed bodies retained','no API key in artifacts','fresh round archives then resets','resume preserves round','independent workspace copy','reset preserves exports','historical exports after reset']},ensure_ascii=False),flush=True)
finally:server.shutdown();server.server_close()
