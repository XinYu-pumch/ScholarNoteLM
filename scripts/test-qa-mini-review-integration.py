"""Real QA worker and shared API retriever against isolated local SSE/embedding fixtures."""
import json,os,sqlite3,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e,storage,qa_service as qa,vector_chunks as chunks,vector_service as vectors
requests=[];stream_started=threading.Event()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(request)
  if 'input' in request:
   value={'data':[{'index':i,'embedding':[1.,.2,.3]} for i,_ in enumerate(request['input'])]}
   self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(value).encode());return
  system=request['messages'][0]['content'];payload=json.loads(request['messages'][-1]['content'])
  if '将用户问题拆解' in system and payload['question']=='你好':value={'route':'chat','aspects':[],'queries':[],'historyRequests':[],'reason':'greeting'}
  elif '将用户问题拆解' in system and payload['question']=='缩短上一条回答':value={'route':'rewrite','aspects':[],'queries':[],'historyRequests':[{'tool':'read_previous_evidence','runId':payload['history'][-1]['runId']}],'reason':'rewrite only'}
  elif 'route=chat' in system:value='你好，请问你想了解什么？'
  elif '将用户问题拆解' in system:value={'aspects':['mechanism','conditions'],'queries':[{'query':'What cellular mechanism was measured?','purpose':'mechanism'},{'query':'What conditions affected the result?','purpose':'conditions'}]}
  elif '逐要点说明支持' in system:value={'enough':True,'coverage':[{'aspect':'mechanism','status':'supported','evidenceIds':['E1'],'gap':''},{'aspect':'conditions','status':'supported','evidenceIds':['E2'],'gap':''}],'queries':[{'query':'Counterevidence for the cellular mechanism '+str(payload['round']),'purpose':'counterevidence'}],'reason':'Enough for a limited answer'}
  else:
   bundle=payload['materialBundle'];node=bundle['unit']['nodes'][0]
   value={'unit_id':bundle['unit']['unit_id'],'sections':[{'node_id':node['node_id'],'title':node['title'],'blocks':[{'type':'markdown','text':'These experiments concern mice [E1] [E2].'},
    {'type':'table','table_id':'T1','title':'Evidence and scope','columns':['Model','Finding'],'rows':[['Mice','A measured change [E1]']],'notes':'Human efficacy was not established.'}]}]}
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  text=value if isinstance(value,str) else json.dumps(value)
  try:
   for i in range(0,len(text),80):
    self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':text[i:i+80]}}]})+'\n\n').encode());self.wfile.flush()
    if i==0 and 'materialBundle' in payload and '逐要点说明支持' not in system and payload['question'] in ('Cancel streaming test','Mutation streaming test'):
     stream_started.set();time.sleep(3)
   self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
old=e.ROOT,e.PROJECT
try:
 with tempfile.TemporaryDirectory(prefix='qa-mini-e2e-',dir=ROOT/'tmp') as folder:
  app=Path(folder);(app/'runtimes').mkdir();(app/'tmp').mkdir()
  for name in ('retrieval','downloader'):(app/'runtimes'/name).symlink_to(ROOT/'runtimes'/name,target_is_directory=True)
  (app/'services').symlink_to(ROOT/'services',target_is_directory=True)
  e.ROOT,e.PROJECT=app,'test';project=storage.project_dir(app,'test')
  e.atomic(project/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><ArticleTitle>Study {pmid}</ArticleTitle><Abstract><AbstractText>Experiments in mice measured immune changes. This evidence does not establish human efficacy. Conditions and limitations require attention.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for pmid in ['123','124','999'])+'</PubmedArticleSet>')
  db=app/'data/research/research.sqlite3';db.parent.mkdir(parents=True)
  profile={'id':'p','name':'Fixture','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','models':['fixture'],'apiKey':'','timeout':15,'temperature':None,'visionModels':[]}
  with sqlite3.connect(db) as c:
   c.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)');c.executemany('INSERT INTO settings VALUES(?,?)',[('profiles',json.dumps([profile])),('activeProfile',json.dumps('p'))])
  qa.rpc(e,'settings.save',{'plannerProfile':'p','plannerModel':'fixture','answerProfile':'p','answerModel':'fixture','minRounds':2,'maxRounds':3,'topK':2})
  vectors.rpc(e,'settings.save',{'baseUrl':profile['baseUrl'],'model':'embed','autoIndex':False});vectors.rpc(e,'test',{})
  thread=qa.rpc(e,'new',{});job=qa.rpc(e,'start',{'threadId':thread['id'],'question':'What does the evidence show?','pmids':['123','124']})
  until=time.monotonic()+50
  while time.monotonic()<until:
   state=qa.job(e,job['id'])
   if state and state['id']==job['id'] and state['state'] not in qa.ACTIVE:break
   time.sleep(.1)
  else:raise AssertionError('Worker did not complete')
  assert state['state']=='done',state.get('error');assert state['round']==2,state
  assert state['citationValidation']['status']=='structural_checked';assert len(state['answerBlocks'])==2
  detail=qa.rpc(e,'get',{'threadId':thread['id']})['runs'][0]
  assert {r['pmid'] for r in detail['evidence']}=={'123','124'}
  assert '[E1]' not in state['answer'] and '(PMID:' in state['answer']
  models=[r for r in requests if 'messages' in r]
  assert len([r for r in models if '选择为解答 question' in r['messages'][0]['content']])==0
  assert len([r for r in models if '逐要点说明支持' in r['messages'][0]['content']])==2
  assert not any({'max_tokens','max_completion_tokens','max_output_tokens'}&set(r) for r in models)
  bundle=json.loads((qa.runpath(e,job['id'])/'answer-bundle.json').read_text());assert len(bundle['evidencePool'])==2
  assert qa.rpc(e,'evidence',{'runId':job['id'],'evidenceId':'E1'})['metadata']['pmid']=='123'
  assert Path(qa.rpc(e,'export',{'threadId':thread['id']})['path']).is_file()
  # Rewrite is a new turn with full dialogue context but only cited evidence, zero searches.
  before=len(requests)
  rewrite=qa.rpc(e,'start',{'threadId':thread['id'],'question':'缩短上一条回答','pmids':['123','124']})
  until=time.monotonic()+30
  while time.monotonic()<until:
   rewrite_state=qa.job(e,rewrite['id'])
   if rewrite_state and rewrite_state['state'] not in qa.ACTIVE:break
   time.sleep(.1)
  assert rewrite_state['state']=='done',rewrite_state.get('error')
  assert rewrite_state['round']==0 and rewrite_state['intent']=='rewrite'
  assert not any('input' in r for r in requests[before:])
  assert len(requests[before:])==2,requests[before:]
  assert len(qa.rpc(e,'get',{'threadId':thread['id']})['runs'])==2
  # Real HTTP polling stays cancellable, and changed material cannot publish.
  for question,expected in [('Cancel streaming test','cancelled'),('Mutation streaming test','failed')]:
   stream_started.clear();pending=qa.rpc(e,'start',{'threadId':thread['id'],'question':question,'pmids':['123','124']})
   assert stream_started.wait(15),'Answer did not start streaming'
   started=time.monotonic()
   if expected=='cancelled':qa.rpc(e,'cancel',{'runId':pending['id']})
   else:
    xml=project/'pubmed/current.xml';e.atomic(xml,xml.read_text().replace('Study 123','Changed study 123'))
   until=time.monotonic()+8
   while time.monotonic()<until:
    result=qa.job(e,pending['id'])
    if result['state'] not in qa.ACTIVE:break
    time.sleep(.05)
   assert result['state']==expected,result.get('error');assert not result.get('answer') and not result.get('draft')
   assert not (qa.runpath(e,pending['id'])/'answer-section.json').exists()
   if expected=='cancelled':assert time.monotonic()-started<2,'Cancellation was blocked by validation'
   else:assert '变化' in result['error'],result['error']
  # A different, empty project can greet without an embedding profile/index being ready.
  e.PROJECT='empty'
  empty_thread=qa.rpc(e,'new',{})
  before=len(requests);hello=qa.rpc(e,'start',{'threadId':empty_thread['id'],'question':'你好'})
  until=time.monotonic()+30
  while time.monotonic()<until:
   hello_state=qa.job(e,hello['id'])
   if hello_state and hello_state['state'] not in qa.ACTIVE:break
   time.sleep(.1)
  assert hello_state['state']=='done',hello_state.get('error')
  assert hello_state['answer'].startswith('你好') and hello_state['round']==0
  assert len(requests[before:])==2 and not any('input' in r for r in requests[before:])
  print(json.dumps({'passed':True,'rounds':state['round'],'modelCalls':len(models),'checks':['real independent worker','shared retriever and embedding API','selected scope','minimum rounds','material deduplication','structured answer and table','PMID binding','source RPC','export','no output token cap','real follow-up rewrite with historical citation binding','greeting in empty project without retrieval','cancel active HTTP within 2 seconds','source mutation while streaming blocks publication']},ensure_ascii=False))
finally:
 e.ROOT,e.PROJECT=old;server.shutdown();server.server_close()
