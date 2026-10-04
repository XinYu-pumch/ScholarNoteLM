import asyncio
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import scihub_altcha as altcha
import scihub_candidates as candidates
import scihub_identity as identity
import scihub_browser as transport
import scihub_retry as retry
import engine
from pdf_fixture import pdf
ROOT=Path(__file__).resolve().parents[3]
DOI='10.1234/test'
TITLE='Classification Criteria for Behcet Disease Uveitis'

class LogicTests(unittest.IsolatedAsyncioTestCase):
    async def test_altcha_algorithms_invalid_work_and_cancellation(self):
        for name,hashfn in altcha.ALGORITHMS.items():
            challenge=dict(algorithm=name,salt='fixture-secret',signature='signature-secret',maxNumber=30,
                           challenge=hashfn(b'fixture-secret17').hexdigest())
            self.assertEqual((await altcha.solve(challenge))['number'],17)
            self.assertIsNone(await altcha.solve({**challenge,'maxNumber':2}))
            self.assertIsNone(await altcha.solve({**challenge,'maxNumber':10**20}))
            self.assertIsNone(await altcha.solve({**challenge,'algorithm':'UNKNOWN'}))
        challenge=dict(algorithm='SHA-256',salt='fixture-secret',signature='secret',maxNumber=1000000,challenge='0'*64)
        task=asyncio.create_task(altcha.solve(challenge));await asyncio.sleep(0);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNone(await altcha.solve(challenge,timeout=0))
    def test_challenge_url_same_origin_only(self):
        self.assertEqual(altcha.challenge_url('<altcha-widget challengeurl="/captcha/challenge/123">','https://a.test/paper'),'https://a.test/captcha/challenge/123')
        self.assertIsNone(altcha.challenge_url('<x challengeurl="https://evil.test/captcha/challenge/1">','https://a.test/paper'))
    def test_candidates_placeholder_unquoted_and_saved_pages(self):
        html='<div class=pdf><object data="data:,"></object></div><meta name=citation_pdf_url content=//a.test/storage/moscow/a.pdf><div class=download><a href=/b.pdf>pdf</a></div>'
        self.assertEqual(candidates.candidates(html,'https://a.test/x'),['https://a.test/storage/moscow/a.pdf','https://a.test/b.pdf'])
        for name in ('afce375d-1141-497f-9de6-8a95d07ecb66.html','e72b6824-6b18-4dbe-a56d-3a6ee8a624a2.html'):
            path=ROOT/'ref'/name
            # The prototype's second URL was synthesized by re-matching the path
            # inside an absolute URL. These snapshots contain one explicit URL.
            if path.exists():self.assertEqual(len(candidates.candidates(path.read_text(),'https://sci-hub.ru/')),1)
    def test_identity_signals_and_bibliography(self):
        self.assertEqual(identity.classify('DOI: '+DOI,DOI)['status'],'match')
        self.assertEqual(identity.classify(TITLE,'10.1234/missing',TITLE)['status'],'match')
        self.assertEqual(identity.classify('',DOI,TITLE)['status'],'unverifiable')
        text='DOI: 10.9999/philosophy\n'+'Philosophy language geography metaphysics. '*100
        self.assertEqual(identity.classify(text,DOI,TITLE)['status'],'mismatch')
        self.assertNotEqual(identity.classify(text+'\nReferences\n'+DOI,DOI,TITLE)['status'],'match')
        self.assertNotEqual(identity.classify(DOI+'extra',DOI)['status'],'match')
        self.assertEqual(identity.classify(DOI+'\nIntroduction',DOI)['status'],'match')
        self.assertEqual(identity.classify('10.1234/\ntest',DOI)['status'],'match')
    async def test_identity_real_pdf_timeout_cancel(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as tmp:
            path=Path(tmp)/'a.pdf';path.write_bytes(pdf(TITLE))
            result=await identity.verify(path,DOI,TITLE)
            self.assertEqual(result['status'],'match');self.assertTrue(result['fileValid'])
            path.write_bytes(pdf(blank=True));self.assertEqual((await identity.verify(path,DOI))['status'],'unverifiable')
            self.assertEqual((await identity.verify(path,DOI,timeout=.001))['reason'],'identity_timeout')
            task=asyncio.create_task(identity.verify(path,DOI));await asyncio.sleep(.001);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,body,status=200,mime='text/html',headers=None):
        if isinstance(body,str):body=body.encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)))
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        path=urlsplit(self.path).path;self.server.calls.append(('GET',path));mode=self.server.mode
        if path.startswith('/captcha/challenge/'):
            if mode=='slow_challenge':time.sleep(3)
            if mode=='challenge_429':return self.send('{}',429,'application/json',{'Retry-After':'600'})
            return self.send(json.dumps(dict(algorithm='SHA-256',salt='secret-salt',signature='secret-signature',maxNumber=30,challenge=hashlib.sha256(b'secret-salt17').hexdigest())),mime='application/json')
        if path.startswith('/entry/'):
            if mode.startswith('challenge') or mode in ('pow','slow_challenge'):
                if 'access=ok' not in self.headers.get('Cookie','') or mode=='challenge_loop':
                    return self.send('<html><body><altcha-widget challengeurl="/captcha/challenge/1"></altcha-widget>captcha</body></html>')
            if mode in ('pow','slow_challenge'):
                return self.send('<html><body><div class=pdf><object data="data:,"></object></div><script>setTimeout(()=>{document.body.innerHTML+=\'<div class="download"><a href="/good.pdf">PDF</a></div>\'},100)</script></body></html>')
            if mode=='multi':return self.send('<object data="data:,"></object><meta name=citation_pdf_url content=/wrong.pdf><div class=download><a href=/title.pdf>Download</a></div>')
            if mode=='pending':return self.send('<div class=download><a href=/blank.pdf>PDF</a></div>')
            if mode=='refresh':
                count=sum(p.startswith('/entry/') for _,p in self.server.calls)
                return self.send('<div class=download><a href="'+('/good.pdf' if count>1 else '/missing.pdf')+'">PDF</a></div>')
            return self.send('<meta name=citation_pdf_url content=/storage/moscow/x.pdf>')
        if path=='/missing.pdf':return self.send('missing',404)
        if path=='/storage/moscow/x.pdf':
            return self.send('busy' if mode=='rate' else 'missing',429 if mode=='rate' else 404,headers={'Retry-After':'600'} if mode=='rate' else {})
        if path in ('/storage/2024/x.pdf','/good.pdf'):return self.send(pdf(DOI),mime='application/pdf',headers={'Content-Disposition':'attachment; filename="paper.pdf"'})
        if path=='/wrong.pdf':return self.send(pdf('DOI: 10.9999/philosophy '+ 'Philosophy language geography metaphysics. '*100),mime='application/pdf')
        if path=='/title.pdf':return self.send(pdf(TITLE),mime='application/pdf')
        if path=='/blank.pdf':return self.send(pdf(blank=True),mime='application/pdf')
        self.send('missing',404)
    def do_POST(self):
        path=urlsplit(self.path).path;self.server.calls.append(('POST',path))
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        solution=json.loads(base64.b64decode(value['captcha']))
        self.server.solutions.append(solution['number'])
        self.send('{"success":true}',mime='application/json',headers={'Set-Cookie':'access=ok; Path=/; HttpOnly; SameSite=Lax'})

class ChromiumEnhancements(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.folder=Path(self.tmp.name)
        self.pool=transport.BrowserPool(ROOT,self.folder)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.calls=[];self.server.solutions=[];self.server.mode='pow'
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    async def asyncTearDown(self):
        await self.pool.close();self.server.shutdown();self.server.server_close()
        self.assertFalse(list(self.folder.glob('scihub-browser-*')));self.tmp.cleanup()
    async def download(self,mode='pow',**kw):
        self.server.mode=mode;self.events=[];self.pending=[]
        return await retry.download(DOI,self.folder/'paper.pdf',[self.url+'/entry'],retry.MirrorHealth(),
            lambda message,**data:self.events.append(data),engine.validate_pdf,session_factory=self.pool.session,title=TITLE,
            budget={'network':0,'wait':0,'networkLimit':10,'waitLimit':1,'deferCooldown':True},
            on_unverifiable=lambda path,evidence,source:self.pending.append(dict(evidence)),**kw)
    async def test_altcha_real_browser_protocol_cookie_reuse_and_dynamic_dom(self):
        info,_,records=await self.download()
        self.assertEqual(info['identity']['status'],'match');self.assertEqual(self.server.solutions,[17])
        self.assertEqual([r['requestType'] for r in records if 'requestType' in r],['challenge_get','challenge_post','challenge_replay'])
        self.assertTrue(all(r['transport']=='playwright-chromium' for r in records))
        self.assertNotIn('secret',json.dumps([records,self.events]))
        await self.download();self.assertEqual(self.server.solutions,[17],'verified batch cookie was not reused')
        # A separate batch has no retained authorization.
        await self.pool.close();self.pool=transport.BrowserPool(ROOT,self.folder)
        await self.download();self.assertEqual(self.server.solutions,[17,17])
    async def test_wrong_candidate_then_title_only_pdf(self):
        info,_,records=await self.download('multi')
        self.assertEqual(info['identity']['reason'],'title_in_frontmatter')
        self.assertIn('identity_mismatch',[r.get('kind') for r in records])
    async def test_scan_preserved_via_pending_callback_never_published(self):
        info,_,records=await self.download('pending')
        self.assertIsNone(info);self.assertEqual(self.pending[0]['status'],'unverifiable')
        self.assertFalse((self.folder/'paper.pdf').exists())
    async def test_shard_rescue_and_no_rate_limit_fanout(self):
        info,_,records=await self.download('shard')
        self.assertEqual(info['shardRescues'],1);self.assertEqual(len(records),3)
        self.server.calls.clear();info,_,records=await self.download('rate')
        self.assertIsNone(info);self.assertEqual(len(records),2)
        self.assertFalse(any('/2024/' in p for _,p in self.server.calls))
    async def test_bounded_refresh(self):
        info,_,records=await self.download('refresh')
        self.assertIsNotNone(info);self.assertEqual(sum(r['role']=='entry' for r in records),2)
    async def test_challenge_429_and_loop_are_bounded(self):
        info,_,records=await self.download('challenge_429')
        self.assertIsNone(info);self.assertEqual(len(records),2)
        self.assertEqual(records[-1]['kind'],'rate_limited')
        self.server.calls.clear();info,_,records=await self.download('challenge_loop')
        self.assertIsNone(info);self.assertEqual(len(records),4)
    async def test_cancel_protocol_closes_page_and_context(self):
        task=asyncio.create_task(self.download('slow_challenge'))
        for _ in range(200):
            if any('/captcha/challenge/' in p for _,p in self.server.calls):break
            await asyncio.sleep(.02)
        self.assertTrue(any('/captcha/challenge/' in p for _,p in self.server.calls))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.server.calls.clear();info,_,_=await self.download('shard');self.assertIsNotNone(info)
