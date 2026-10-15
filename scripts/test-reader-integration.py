"""Rust RPC + detached reader + local SSE server; --serve keeps an isolated UI fixture."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys,tempfile,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'services/downloader'),str(ROOT/'services/downloader/tests')]
import engine as e,storage
from test_scihub_retry import pdf
import provider_fixture as pf
requests=[];started=threading.Event()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  req=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(req);pf.capture(self.headers,req);question=req['messages'][-1]['content']
  if question=='CONTEXT_ERROR':self.send_response(400);self.end_headers();self.wfile.write(b'{"error":"context length exceeded"}');return
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  try:
   text='根据这篇文献的材料，研究报告了实验结果。\n\n这是本地模拟回答，用于验证阅读聊天；没有调用真实模型。'
   for i in range(0,len(text),8):
    self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':text[i:i+8]}}]})+'\n\n').encode());self.wfile.flush();started.set();time.sleep(.2 if question!='CANCEL' else 1)
   self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
  except (BrokenPipeError,ConnectionResetError):pass

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--serve',action='store_true');args=parser.parse_args()
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 with tempfile.TemporaryDirectory(prefix='reader-e2e-',dir=ROOT/'tmp') as folder:
  app=Path(folder);(app/'tmp').mkdir()
  for name in ('services','runtimes'):(app/name).symlink_to(ROOT/name,target_is_directory=True)
  pf.setup(app,ROOT,f'http://127.0.0.1:{server.server_port}/v1',['fixture-chat', 'fixture-other'])
  e.ROOT,e.PROJECT=app,'reader_test';env={**os.environ,'SCHOLARNOTELM_ROOT':str(app)}
  def rpc(action,**a):
   proc=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':{'project':e.PROJECT,**a}}),text=True,capture_output=True,env=env,timeout=30)
   data=json.loads(proc.stdout);assert data.get('ok'),data;return data['data']
  project={'id':e.PROJECT,'name':'阅读功能隔离测试','description':'仅模拟材料与本地模型','color':'sage','papers':[],'messages':[],'sections':[],'notes':{'PMID-1':'已有手写笔记，应保留。'},'tasks':[]}
  rpc('storage.initialize');rpc('storage.register',folder='ReaderTest',data=project);rpc('storage.state.write',state={'version':1,'active':e.PROJECT,'theme':'light','projects':[project]})
  base=storage.project_dir(app,e.PROJECT)
  xml='<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>{title}</ArticleTitle><Journal><Title>Reader testing journal</Title><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal><Abstract><AbstractText>Abstract only evidence. This is an isolated fixture, not a scientific claim.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for p,title in [('1','Full text study — PDF 阅读测试'),('2','Abstract only study — 摘要阅读测试'),('3','Pending conversion — 尚未转换')])+'</PubmedArticleSet>'
  rpc('xml.import',name='Reader fixture',xml=xml)
  # Eight text pages, valid PDF with no dependency on downloaded papers.
  from pypdf import PdfWriter
  from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
  writer=PdfWriter()
  font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
  font_ref=writer._add_object(font)
  for n in range(1,9):
   page=writer.add_blank_page(width=600,height=800)
   page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font_ref})})
   lines=[f'Reading workspace - test paper / page {n}','Introduction','','Full text reading and per-paper conversations.','This PDF contains a selectable text layer.','Search for evidence.','','Methods','','The test verifies raw Markdown, references and captions.','','Results','','Complete source and conversation history are supplied.']
   content=DecodedStreamObject();content.set_data(('BT /F1 15 Tf 55 735 Td 28 TL '+' '.join(('T* ' if i else '')+'('+line+') Tj' for i,line in enumerate(lines))+' ET').encode())
   page[NameObject('/Contents')]=writer._add_object(content)
  writer.write(base/'pdf/1.pdf');e.atomic(base/'pdf/3.pdf',pdf())
  raw='FULL_RAW_START\n# Results\n'+'Original fulltext evidence. '*12000+'\n# References\nRAW_END_REFERENCE'
  e.atomic(base/'markdown/raw/1.md',raw);e.atomic(base/'markdown/1.md','CLEANED_NEVER_SEND');e.write_json(base/'metadata/markdown/1.json',{'pdfSha256':e.validate_pdf(base/'pdf/1.pdf')['sha256'],'rawSha256':hashlib.sha256(raw.encode()).hexdigest()})
  with sqlite3.connect(app/'data/research/research.sqlite3') as c:
   profile=pf.profile({'id':'fixture','name':'本地模拟模型','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture-chat','models':['fixture-chat','fixture-other'],'apiKey':'','timeout':20,'temperature':None})
   c.executemany('INSERT OR REPLACE INTO settings VALUES(?,?)',[('profiles',json.dumps([profile])),('activeProfile',json.dumps('fixture')),('mesh',json.dumps({'autoUpdate':False}))])
  def wait(t):
   deadline=time.monotonic()+30
   while time.monotonic()<deadline:
    t=rpc('reader.get',id=t['id'])
    if t['state'] not in ('queued','running','stopping'):return t
    time.sleep(.1)
   raise AssertionError('worker timed out')
  a=rpc('reader.new',pmid='1');a=wait(rpc('reader.start',id=a['id'],question='Summarize',model='fixture-chat'));assert a['state']=='done',a['error']
  assert 'FULL_RAW_START' in requests[-1]['messages'][1]['content'] and 'RAW_END_REFERENCE' in requests[-1]['messages'][1]['content']
  assert 'CLEANED_NEVER_SEND' not in json.dumps(requests[-1]);assert len(requests[-1]['messages'][1]['content'])>200000
  a=wait(rpc('reader.start',id=a['id'],question='Follow-up',model='fixture-other'));assert a['state']=='done';assert requests[-1]['model']=='fixture-other';assert len(requests[-1]['messages'])==5
  fork=rpc('reader.fork',id=a['id'],turnId=a['messages'][0]['id']);assert len(fork['messages'])==1 and fork['source']==a['source']
  fork=wait(rpc('reader.start',id=fork['id'],question='Branch follow-up'));assert fork['state']=='done';assert requests[-1]['messages'][-3]['content']=='Summarize';assert 'Follow-up' not in [m['content'] for m in requests[-1]['messages']]
  regen=wait(rpc('reader.start',id=a['id'],retry=True,turnId=a['messages'][0]['id']));assert regen['state']=='done' and regen['id']!=a['id'];assert len(requests[-1]['messages'])==3
  assert len(rpc('reader.get',id=a['id'])['messages'])==2
  b=rpc('reader.new',pmid='1');b=wait(rpc('reader.start',id=b['id'],question='Independent'));assert a['source']==b['source'];assert len(list((base/'reader/sources').glob('*.gz')))==1
  c=rpc('reader.new',pmid='2');c=wait(rpc('reader.start',id=c['id'],question='Abstract'));assert c['sourceKind']=='abstract';assert '仅摘要' in requests[-1]['messages'][1]['content']
  started.clear();c=rpc('reader.start',id=c['id'],question='CANCEL');assert started.wait(5);rpc('reader.cancel',id=c['id']);c=wait(c);assert c['state']=='cancelled' and c['messages'][-1]['text']
  c=wait(rpc('reader.start',id=c['id'],retry=True));assert c['state']=='done' and len(c['messages'])==2
  c=wait(rpc('reader.start',id=c['id'],question='CONTEXT_ERROR'));assert c['state']=='failed' and '全文不会自动截断' in c['error']
  rpc('reader.rename',id=b['id'],name='Shared snapshot');rpc('reader.delete',id=b['id']);assert (base/'reader/sources'/f"{a['source']}.json.gz").exists()
  assert not list((base/'reader').rglob('*.pdf')) and not list((base/'reader').rglob('*.md'))
  if pf.ENABLED:
   ids=pf.sessions();assert ids[0]==ids[1] and len(set([ids[0],*ids[2:6]]))==5
   assert len(set(ids[5:]))==1,'Reader cancellation/retry changed session'
  pf.verify()
  print(json.dumps({'result':'PASS','checks':'full raw >200k chars, multi-turn, model switching, shared snapshots, abstract fallback, cancellation, retry, context overflow, Rust RPC','requests':len(requests)},ensure_ascii=False),flush=True)
  if args.serve:
   print('UI_FIXTURE_ROOT='+str(app),flush=True)
   try:
    while True:time.sleep(1)
   except KeyboardInterrupt:pass
 server.shutdown()
if __name__=='__main__':main()
