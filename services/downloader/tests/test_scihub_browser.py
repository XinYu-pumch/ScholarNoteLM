"""Real bundled headless Chromium against a local fixture; no internet traffic."""
import asyncio,hashlib,io,json,os,signal,sys,tempfile,threading,time,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scihub_browser as transport
import scihub_retry as retry
import engine as e
from pypdf import PdfWriter
ROOT=Path(__file__).resolve().parents[3]
buffer=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(buffer);PDF=buffer.getvalue()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        route=urlsplit(self.path).path;self.server.calls.append((route,self.headers.get('Cookie','')))
        status=200;body=b'<html>no paper</html>';headers={'Content-Type':'text/html'}
        if route=='/js':
            headers['Set-Cookie']='fixture=yes; Path=/'
            body=b'''<html><script>setTimeout(()=>document.body.innerHTML='<div class="pdf"><iframe src="/cookie.pdf?token=SECRET"></iframe></div>',100)</script></html>'''
        elif route=='/challenge':body=b'<html><title>Checking your browser</title>captcha</html>'
        elif route in ('/403','/429'):status=int(route[1:]);headers['Retry-After']='120'
        elif route in ('/inline.pdf','/attachment.pdf','/cookie.pdf','/slow.pdf'):
            headers['Content-Type']='application/pdf';body=PDF
            if route=='/cookie.pdf' and 'fixture=yes' not in self.headers.get('Cookie',''):status=403;body=b'cookie missing'
            if route=='/attachment.pdf':headers['Content-Disposition']='attachment; filename="fixture.pdf"'
        elif route=='/fake.pdf':headers['Content-Type']='application/pdf';body=b'<html>not a PDF</html>'
        elif route=='/hang':time.sleep(4)
        self.send_response(status)
        for k,v in headers.items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:
            if route=='/slow.pdf':self.wfile.write(body[:5]);self.wfile.flush();time.sleep(4);self.wfile.write(body[5:])
            else:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass

class BrowserTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.server.calls=[]
        threading.Thread(target=cls.server.serve_forever,daemon=True).start();cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.pool=transport.BrowserPool(ROOT,Path(self.temp.name));self.server.calls.clear()
    async def asyncTearDown(self):
        await self.pool.close()
        self.assertFalse(list(Path(self.temp.name).iterdir()))
        if self.pool.process:self.assertIsNotNone(self.pool.process.returncode)
        self.temp.cleanup()
    async def request(self,name,**kwargs):
        async with self.pool.session() as s:return await s.get(self.url+name,kwargs.get('timeout',5),role=kwargs.get('role','entry'))
    async def test_rendered_dom_cookie_session_and_pdf_semaphore_boundary(self):
        async with self.pool.session() as s:
            r=await s.get(self.url+'/js',5)
            self.assertIn('cookie.pdf',r.text);self.assertEqual(r.method,'browser-rendered-dom')
            self.assertFalse(any(route=='/cookie.pdf' for route,_ in self.server.calls),'automatic iframe bypassed file scheduler')
            r=await s.get(self.url+'/cookie.pdf?token=SECRET',5,role='file')
            self.assertEqual(r.content,PDF);self.assertEqual(r.metrics['transport'],'playwright-chromium')
        # A different article gets no cookies, while retaining the same browser PID.
        pid=self.pool.browser_pid;r=await self.request('/cookie.pdf');self.assertEqual(r.status_code,403);self.assertEqual(self.pool.browser_pid,pid)
    async def test_inline_and_attachment_scan_is_valid_but_identity_pending(self):
        for route in ('/inline.pdf','/attachment.pdf'):
            r=await self.request(route,role='file');self.assertEqual(r.content,PDF);self.assertIn(r.method,('browser-download','browser-response-body'))
        dest=Path(self.temp.name)/'checked.pdf';events=[]
        info,_,requests=await retry.download('10.1/test',dest,[self.url+'/inline.pdf#'],retry.MirrorHealth(),lambda msg,**kw:events.append(kw),e.validate_pdf,known_files=[{'url':self.url+'/inline.pdf','sha256':hashlib.sha256(PDF).hexdigest()}],session_factory=self.pool.session,budget={'network':0,'wait':0,'networkLimit':5,'waitLimit':1})
        self.assertIsNone(info);self.assertEqual(requests[0]['kind'],'identity_unverifiable');self.assertFalse(dest.exists())
    async def test_challenge_status_and_non_pdf_classification(self):
        for route,kind in [('/challenge','suspected_challenge'),('/403','forbidden'),('/429','rate_limited')]:
            # A known page is requested exactly as provided; no DOI appended.
            _,_,records=await retry.download('10.1/test',Path(self.temp.name)/'failed.pdf',[],retry.MirrorHealth(),lambda *a,**k:None,e.validate_pdf,known_pages=[self.url+route],session_factory=self.pool.session,budget={'network':0,'wait':0,'networkLimit':6,'waitLimit':1,'deferCooldown':True})
            self.assertEqual(records[0]['kind'],kind)
        _,_,records=await retry.download('10.1/test',Path(self.temp.name)/'failed.pdf',[],retry.MirrorHealth(),lambda *a,**k:None,e.validate_pdf,known_files=[{'url':self.url+'/fake.pdf'}],session_factory=self.pool.session,budget={'network':0,'wait':0,'networkLimit':5,'waitLimit':1})
        self.assertEqual(records[0]['kind'],'non_pdf');self.assertFalse((Path(self.temp.name)/'failed.pdf').exists())
    async def test_complete_body_and_navigation_timeout_cleanup(self):
        await self.request('/inline.pdf')
        for route in ('/slow.pdf','/hang'):
            started=time.monotonic()
            with self.assertRaises((TimeoutError,transport.BrowserError)):await self.request(route,timeout=.3)
            self.assertLess(time.monotonic()-started,2)
        r=await self.request('/attachment.pdf');self.assertEqual(r.content,PDF)
    async def test_cancel_download_and_release_context(self):
        await self.request('/inline.pdf')
        task=asyncio.create_task(self.request('/slow.pdf'));await asyncio.sleep(.2);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual((await self.request('/inline.pdf')).content,PDF)
    async def test_timed_out_request_does_not_poison_later_mirror_in_same_session(self):
        async with self.pool.session() as session:
            await session.get(self.url+'/inline.pdf',5)
            key=session.key
            with self.assertRaises((TimeoutError,transport.BrowserError)):
                await session.get(self.url+'/slow.pdf',.2,role='file')
            self.assertNotEqual(key,session.key)
            self.assertEqual((await session.get(self.url+'/attachment.pdf',5,role='file')).content,PDF)
    async def test_sidecar_crash_no_http_fallback(self):
        await self.request('/inline.pdf');pid=self.pool.browser_pid
        task=asyncio.create_task(self.request('/slow.pdf'));await asyncio.sleep(.2);self.pool.process.kill()
        with self.assertRaisesRegex(transport.BrowserError,'异常|通信'):await task
        with self.assertRaises(transport.BrowserError):await self.request('/inline.pdf')
        for _ in range(30):
            if not e.process_alive(pid):break
            await asyncio.sleep(.05)
        self.assertFalse(e.process_alive(pid))
    async def test_cancel_during_launch_leaves_no_session(self):
        task=asyncio.create_task(self.request('/hang'));await asyncio.sleep(.01);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        await self.pool.close()
    async def test_chromium_crash_is_reported(self):
        await self.request('/inline.pdf')
        task=asyncio.create_task(self.request('/slow.pdf'));await asyncio.sleep(.15)
        if os.name=='nt':
            import subprocess
            subprocess.run(['taskkill','/PID',str(self.pool.browser_pid),'/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
        else:os.kill(self.pool.browser_pid,signal.SIGKILL)
        with self.assertRaises(transport.BrowserError):await task
    async def test_worker_abrupt_exit_closes_browser_and_temporary_profile(self):
        code="""import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);from scihub_browser import BrowserPool
async def main():
 pool=BrowserPool(Path(sys.argv[2]),Path(sys.argv[3]))
 async with pool.session() as session:await session.get(sys.argv[4],5)
 print(json.dumps({'node':pool.process.pid,'browser':pool.browser_pid,'directory':str(pool.directory)}),flush=True)
 await asyncio.sleep(30)
asyncio.run(main())
"""
        child=await asyncio.create_subprocess_exec(sys.executable,'-c',code,str(ROOT/'services/downloader'),str(ROOT),self.temp.name,self.url+'/inline.pdf',stdout=asyncio.subprocess.PIPE)
        try:
            receipt=json.loads(await asyncio.wait_for(child.stdout.readline(),8))
            child.kill();await child.wait()
            for _ in range(60):
                if not Path(receipt['directory']).exists() and not e.process_alive(receipt['browser']):break
                await asyncio.sleep(.05)
            self.assertFalse(Path(receipt['directory']).exists())
            self.assertFalse(e.process_alive(receipt['browser']))
        finally:
            if child.returncode is None:child.kill();await child.wait()
    async def test_logs_drop_signed_parameters(self):
        events=[]
        _,_,records=await retry.download('10.1/test',Path(self.temp.name)/'failed.pdf',[],retry.MirrorHealth(),lambda msg,**kw:events.append(kw),e.validate_pdf,known_pages=[self.url+'/challenge?token=SECRET'],session_factory=self.pool.session,budget={'network':0,'wait':0,'networkLimit':5,'waitLimit':1})
        self.assertNotIn('SECRET',json.dumps([records,events]));self.assertEqual(records[0]['transport'],'playwright-chromium')

if __name__=='__main__':unittest.main()
