"""Real Chromium + httpx stack, isolated project, 38 articles; no external requests."""
import asyncio,io,json,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/downloader'))
import engine as e
import compact_io
import scihub_retry as s
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/downloader/tests'))
from pdf_fixture import pdf as make_pdf
e.load_sources();root=e.ROOT;fixture=Path(tempfile.mkdtemp(prefix='scheduler-http-',dir=root/'tmp'));e.ROOT=fixture;e.PROJECT='p'
(fixture/'runtimes').symlink_to(root/'runtimes',target_is_directory=True)
calls=[]
active={};peaks={};total_peak=0;guard=threading.Lock()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  global total_peak
  if self.path=='/slow.pdf':
   self.send_response(200);self.send_header('Content-Length','10000');self.end_headers()
   try:
    for _ in range(100):self.wfile.write(b'x'*100);self.wfile.flush();time.sleep(.02)
   except (BrokenPipeError,ConnectionResetError):pass
   return
  p=self.path.rsplit('/',1)[-1];item=e.one('SELECT stage FROM items WHERE pmid=?',(p,));stage=item['stage'];calls.append({'stage':stage,'pmid':p,'path':self.path})
  port=str(self.server.server_port)
  with guard:
   active[port]=active.get(port,0)+1;peaks[port]=max(peaks.get(port,0),active[port]);total_peak=max(total_peak,sum(active.values()))
  time.sleep(.015)
  status=200;content=b'<html><title>Are you a robot?</title>captcha</html>';mime='text/html'
  if stage=='scihub_retry':
   if int(p)<117:content=make_pdf('10.1/'+p);mime='application/pdf'
   else:status=403;content=b'Forbidden'
  # End measurement before the response unblocks the client and the next request.
  with guard:active[port]-=1
  self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
servers=[ThreadingHTTPServer(('127.0.0.1',0),Handler) for _ in range(2)]
threads=[threading.Thread(target=server.serve_forever,daemon=True) for server in servers]
for thread in threads:thread.start()
async def unavailable(*args):return None,'no PDF in fixture'
try:
 bases=['http://127.0.0.1:'+str(server.server_port) for server in servers];e.save_settings({'mirrors':bases})
 with patch.object(e,'launch'):b=e.create({'project':'p','papers':[{'pmid':str(p),'doi':'10.1/'+str(p)} for p in range(100,138)]})
 e.atomic(e.storage.project_dir(e.ROOT,e.PROJECT)/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/{p}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>' for p in range(100,138))+'</PubmedArticleSet>')
 b=e.one('SELECT * FROM batches');bloom=SimpleNamespace(contains=lambda doi:int(doi.rsplit('/',1)[-1])<117,close=lambda:None)
 with patch.object(e,'bloom_info',return_value={}),patch.object(e.badr,'SciHubBloomFilter',return_value=bloom),patch.object(e,'source_unpaywall',unavailable),patch.object(e,'source_s3',unavailable),patch.object(s,'FIRST_DELAY',(.1,.1)):
  asyncio.run(e.run_batch(b))
 report=json.loads(compact_io.read_text((e.batch_dir(b)/'download_report.json')));first=[c for c in calls if c['stage']=='scihub_bloom'];second=[c for c in calls if c['stage']=='scihub_retry']
 assert len(first)==34 and len({c['pmid'] for c in first})==17
 assert len(second)==59 and {int(c['pmid']) for c in second[:17]}==set(range(100,117))
 assert all(int(c['pmid'])>=117 for c in second[17:])
 assert report['bloomSummary']['retrySuccess']==17 and report['counts']=={'success':17,'failed':21}
 assert all(v==1 for v in peaks.values()) and total_peak==2,(peaks,total_peak)
 async def streaming_check():
  path=fixture/'slow.pdf';detail={};token=e.HTTP_TRACE.set((b,'100','unpaywall',detail))
  started=time.monotonic()
  try:
   async with e.httpx.AsyncClient() as client:
    try:
     async with asyncio.timeout(.1):await e.fetch_pdf(client,bases[0]+'/slow.pdf',path,b,'100','unpaywall')
    except TimeoutError:pass
    else:raise AssertionError('Trickling response was not bounded')
   assert not path.exists()
   assert detail['fileRequests']==1 and detail['requests'][0]['bytes']>0
   assert time.monotonic()-started<.5
   return detail
  finally:e.HTTP_TRACE.reset(token)
 stream=asyncio.run(streaming_check())
 (root/'docs/SCHEDULER_HTTP_TEST.json').write_text(json.dumps({'passed':True,'version':'0.5.3','fixture':str(fixture),'transport':'real curl_cffi and httpx -> local HTTP servers','articles':38,'bloomHits':17,'bloomFirstEntryRequests':len(first),'bloomRetrySuccess':17,'nonBloomRequestsOnlyAfterBloom':True,'perMirrorPeak':peaks,'crossMirrorPeak':total_peak,'slowStreamCancelled':True,'slowStreamRequests':stream['requests'],'externalRequests':0,'summary':report['bloomSummary']},indent=2))
 print('Real HTTP 38-article scheduler regression passed: all 17 Bloom hits recovered before 21 nonhits.')
finally:
 for server in servers:server.shutdown();server.server_close()
 for thread in threads:thread.join()
