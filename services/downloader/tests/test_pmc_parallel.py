"""Offline tests for opposing queues, source handoff and direct getPdf streaming."""
import asyncio
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as e
import europe_pmc_pdf as epmc
import pmc_parallel
e.load_sources()
import httpx
from pdf_fixture import pdf


def content():
    return pdf('PMC test article ' + 'x' * 1500)


class PmcTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=e.ROOT / 'tmp')
        self.original = e.ROOT, e.PROJECT
        e.ROOT, e.PROJECT = Path(self.tmp.name), 'p'
        e.save_settings({'mirrors': [], 'zoteroAddress': '', 'email': ''})

    def tearDown(self):
        e.ROOT, e.PROJECT = self.original
        self.tmp.cleanup()

    def batch(self, numbers=(1, 2, 3), **cfg):
        papers = [{'pmid': str(n), 'pmcid': f'PMC{n}', 'title': f'Paper {n}'} for n in numbers]
        with patch.object(e, 'launch'):
            result = e.create({'project': 'p', 'papers': papers})
        b = e.one('SELECT * FROM batches WHERE id=?', (result['id'],))
        config = {**json.loads(b['config']), **cfg}
        e.execute('UPDATE batches SET config=? WHERE id=?', (json.dumps(config), b['id']))
        return e.one('SELECT * FROM batches WHERE id=?', (b['id'],))

    def result(self, b):
        return json.loads((e.batch_dir(b) / 'download_report.json').read_text())

    async def unavailable(self, *args):
        return None, 'not found'

    def client(self, handler):
        original = httpx.AsyncClient
        return patch.object(e.httpx, 'AsyncClient', side_effect=lambda **kw:
                            original(transport=httpx.MockTransport(handler), **kw))

    async def test_opposing_numeric_order_and_fixed_worker_limits_no_duplicate_download(self):
        b = self.batch((10, 2, 20, 3, 30, 4, 40, 5, 50, 1))
        calls = {'s3': [], 'getPdf': []}
        active = set()
        peak = Counter()
        counts = Counter()
        all_started = asyncio.Event()

        async def source(kind, client, paper, path, batch, cfg, *args):
            p = paper['pmid']
            self.assertNotIn(p, active)
            active.add(p)
            calls[kind].append(int(p))
            counts[kind] += 1
            peak[kind] = max(peak[kind], counts[kind])
            if len(active) == 9:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), 2)
            await asyncio.sleep(.005)
            path.write_bytes(content())
            active.remove(p)
            counts[kind] -= 1
            return {'source': kind}, ''

        async def s3(*args): return await source('s3', *args)
        async def getpdf(*args): return await source('getPdf', *args)
        with patch.object(e, 'source_s3', s3), patch.object(e, 'source_europe_pmc_getpdf', getpdf):
            await asyncio.wait_for(e.run_batch(b), 4)
        self.assertEqual(calls['s3'][:5], [1, 2, 3, 4, 5])
        self.assertEqual(calls['getPdf'][:4], [50, 40, 30, 20])
        self.assertEqual(peak, {'s3': 5, 'getPdf': 4})
        self.assertEqual(Counter(calls['s3'] + calls['getPdf']), Counter([1,2,3,4,5,10,20,30,40,50]))
        report = self.result(b)
        self.assertEqual(report['counts'], {'success': 10})
        self.assertGreater(report['pmcParallelWallSeconds'], 0)

    async def test_mutual_fallback_while_other_source_is_still_working(self):
        b = self.batch(pmcConcurrency=1, europePmcConcurrency=1)
        rescued = asyncio.Event()
        s3_busy = asyncio.Event()
        calls = []

        async def s3(client, paper, path, batch, cfg):
            p = paper['pmid']; calls.append(('s3', p))
            if p == '1':
                return None, 'S3 timed out'
            if p == '2':
                s3_busy.set()
                await asyncio.wait_for(rescued.wait(), 2)
            path.write_bytes(content())
            return {'source': 'PMC S3'}, ''

        async def getpdf(client, paper, path, batch, cfg, gate):
            p = paper['pmid']; calls.append(('getPdf', p))
            if p == '3':
                await s3_busy.wait()
                return None, 'HTTP 404'
            self.assertEqual(p, '1')
            self.assertTrue(s3_busy.is_set())
            path.write_bytes(content()); rescued.set()
            return {'source': 'Europe PMC getPdf'}, ''

        with patch.object(e, 'source_s3', s3), patch.object(e, 'source_europe_pmc_getpdf', getpdf):
            await asyncio.wait_for(e.run_batch(b), 4)
        self.assertEqual(self.result(b)['counts'], {'success': 3})
        self.assertEqual(Counter(calls), Counter([('s3','1'),('s3','2'),('s3','3'),('getPdf','3'),('getPdf','1')]))

    async def test_both_fail_then_downstream_and_no_repeated_source(self):
        b = self.batch((1, 2), pmcConcurrency=1, europePmcConcurrency=1)
        calls = []
        async def sci(paper, *args):
            prior = e.progress(b['id'], paper['pmid'])['completedStages']
            self.assertIn('pmc_s3', prior); self.assertIn('europe_pmc_getpdf', prior)
            calls.append(paper['pmid'])
            return None, 'no mirrors', 'skipped'
        with patch.object(e,'source_s3',self.unavailable), patch.object(e,'source_europe_pmc_getpdf',self.unavailable), patch.object(e,'source_scihub',sci):
            await e.run_batch(b)
        self.assertEqual(self.result(b)['counts'], {'failed': 2})
        pairs = Counter((a['pmid'],a['stage']) for a in self.result(b)['attempts'] if a['stage'] in ('pmc_s3','europe_pmc_getpdf'))
        self.assertEqual(len(pairs), 4); self.assertEqual(set(pairs.values()), {1})
        self.assertEqual(len(calls), 4)

    async def test_completed_s3_stage_on_resume_still_allows_getpdf(self):
        b = self.batch((1,))
        e.save_progress(b['id'], '1', {'completedStages': ['pmc_s3']})
        async def getpdf(client, paper, path, *args):
            path.write_bytes(content()); return {'source': 'Europe PMC getPdf'}, ''
        with patch.object(e,'source_s3',side_effect=AssertionError('S3 must not replay')), patch.object(e,'source_europe_pmc_getpdf',getpdf):
            await e.run_batch(b)
        self.assertEqual(self.result(b)['counts'], {'success': 1})

    async def test_only_existing_valid_pmcids_enter_pair_without_pmid_lookup(self):
        b = self.batch((1, 2, 3), pmcConcurrency=1, europePmcConcurrency=1)
        for p, pmcid in [('2', ''), ('3', 'PMC-invalid')]:
            e.execute('UPDATE items SET paper=? WHERE batch=? AND pmid=?',
                      (json.dumps({'pmid':p, 'pmcid':pmcid}), b['id'], p))
        requests = []
        async def handler(req):
            requests.append(str(req.url))
            if req.url.host == 'pmc-oa-opendata.s3.amazonaws.com':
                self.assertEqual(req.url.params['prefix'], 'PMC1.')
                return httpx.Response(200,text='<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>')
            self.assertEqual(req.url.path, '/api/getPdf')
            self.assertEqual(req.url.params['pmcid'], 'PMC1')
            return httpx.Response(200,content=content())
        with self.client(handler):
            await e.run_batch(b)
        report = self.result(b)
        self.assertEqual(report['counts'], {'success':1, 'failed':2})
        self.assertEqual(len(requests), 2)
        attempts = [a for a in report['attempts'] if a['stage'] in ('pmc_s3','europe_pmc_getpdf')]
        self.assertEqual({a['pmid'] for a in attempts}, {'1'})
        for p in ('2','3'):
            self.assertIn('scihub_bloom',e.progress(b['id'],p)['completedStages'])
            self.assertNotIn('pmc_s3',e.progress(b['id'],p)['completedStages'])

    async def test_missing_pmcid_skips_entire_pair_and_direct_s3_makes_no_request(self):
        b=self.batch((1,))
        e.execute('UPDATE items SET paper=? WHERE batch=?',(json.dumps({'pmid':'1'}),b['id']))
        async def forbidden(req):raise AssertionError('Must not request or resolve PMCID')
        with self.client(forbidden):
            await e.run_batch(b)
        report=self.result(b)
        self.assertFalse(any(r['stage'].startswith('pmc') or r['stage']=='europe_pmc_getpdf' for r in report['stageRuns']))
        self.assertEqual(report['pmcParallelWallSeconds'],0)
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            info,reason=await e.source_s3(client,{'pmid':'1'},e.ROOT/'unused.pdf',b,e.config())
        self.assertIsNone(info);self.assertEqual(reason,'没有有效 PMCID')

    async def test_cancel_both_active_sources_cleans_partial_files_and_can_resume(self):
        b = self.batch((1, 2), pmcConcurrency=1, europePmcConcurrency=1)
        entered = set(); both = asyncio.Event()
        async def slow(kind, client, paper, path, *args):
            path.write_bytes(b'%PDF-partial'); entered.add(kind)
            if len(entered) == 2: both.set()
            await asyncio.sleep(60)
        async def s3(*args):return await slow('s3',*args)
        async def getpdf(*args):return await slow('getPdf',*args)
        with patch.object(e,'source_s3',s3), patch.object(e,'source_europe_pmc_getpdf',getpdf):
            task = asyncio.create_task(e.monitored(b))
            await asyncio.wait_for(both.wait(),2)
            e.execute("UPDATE batches SET control='cancel' WHERE id=?",(b['id'],))
            await asyncio.wait_for(task,2)
        self.assertEqual(self.result(b)['state'], 'cancelled')
        self.assertEqual(self.result(b)['counts'], {'cancelled':2})
        self.assertFalse(list((e.batch_dir(b)/'staging').rglob('*.pdf')))
        for p in ('1','2'):self.assertFalse(e.progress(b['id'],p).get('completedStages'))
        with patch.object(e,'launch'):e.control({'project':'p','id':b['id'],'command':'resume'})
        async def success(client,paper,path,*args):
            path.write_bytes(content());return {'source':'resumed'},''
        with patch.object(e,'source_s3',success), patch.object(e,'source_europe_pmc_getpdf',success):
            await e.run_batch(e.one('SELECT * FROM batches'))
        self.assertEqual(self.result(b)['counts'], {'success':2})

    async def test_existing_pdf_reused_and_fast_oa_switch_disables_both_routes(self):
        b = self.batch((1,2), fastOa=False)
        dest=e.paper_dir('p','1')/'1.pdf';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(content())
        with patch.object(e,'source_s3',side_effect=AssertionError('disabled')), patch.object(e,'source_europe_pmc_getpdf',side_effect=AssertionError('disabled')):
            await e.run_batch(b)
        self.assertEqual(self.result(b)['counts'], {'skipped':1,'failed':1})

    async def test_getpdf_status_policy_and_pdf_validation(self):
        for status, body, succeeds in [(200,content(),True),(200,b'<html>'+b'x'*1200,False),(200,b'%PDF-too-small',False),(404,b'{"error":"No PDF file found"}',False),(403,b'forbidden',False)]:
            with self.subTest(status=status,valid=succeeds):
                b=self.batch((1,))
                calls=[]
                async def handler(req):
                    calls.append(req)
                    self.assertEqual(str(req.url),'https://europepmc.org/api/getPdf?pmcid=PMC1')
                    return httpx.Response(status,content=body)
                with self.client(handler), patch.object(e,'source_s3',self.unavailable):
                    await e.run_batch(b)
                self.assertEqual(len(calls),1)
                report=self.result(b)
                self.assertEqual(report['counts'], {'success':1} if succeeds else {'failed':1})
                a=next(a for a in report['attempts'] if a['stage']=='europe_pmc_getpdf')
                self.assertEqual(a['detail']['fileRequests'],1)
                self.assertIn('pmcid=PMC1',a['detail']['requests'][0]['url'])
                if status>=400:self.assertIn('error',a['detail']['requests'][0])
                self.assertFalse(list((e.batch_dir(b)/'staging').rglob('*.pdf')))
                # Isolate subcases, including their existing-PDF reuse state.
                (e.paper_dir('p','1')/'1.pdf').unlink(missing_ok=True)

    async def test_getpdf_retries_500_twice_then_success_and_persists_attempt_budget(self):
        b=self.batch((1,));path=e.ROOT/'test.pdf';calls=[];detail={}
        async def handler(req):
            calls.append(req)
            return httpx.Response(500, json={'errMsg':'Failed to retrieve PDF'}) if len(calls)<3 else httpx.Response(200,content=content())
        token=e.HTTP_TRACE.set((b,'1','europe_pmc_getpdf',detail))
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with patch.object(epmc.asyncio,'sleep',new_callable=AsyncMock) as sleep:
                    info,_=await e.source_europe_pmc_getpdf(client,{'pmid':'1','pmcid':' pmc0001 '},path,b,e.config(),epmc.RateGate())
            self.assertEqual(info['pmcid'],'PMC1');self.assertEqual(len(calls),3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list],[2,4])
            self.assertEqual([r['attempt'] for r in detail['requests']],[1,2,3])
            self.assertEqual(e.progress(b['id'],'1')['getPdfAttempts'],3)
        finally:e.HTTP_TRACE.reset(token)

    async def test_long_429_retry_after_stops_all_getpdf_workers_without_touching_s3(self):
        b=self.batch((1,2));gate=epmc.RateGate();calls=[]
        async def handler(req):
            calls.append(req);return httpx.Response(429,headers={'Retry-After':'600'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for p in ('1','2'):
                with self.assertRaises(epmc.Deferred):
                    await e.source_europe_pmc_getpdf(client,{'pmid':p,'pmcid':f'PMC{p}'},e.ROOT/f'{p}.pdf',b,e.config(),gate)
        self.assertEqual(len(calls),1)
        # A paused worker must not forget Retry-After when it starts again.
        restored=epmc.RateGate(e.progress(b['id'],'1')['getPdfNextAttemptAt'])
        with self.assertRaises(epmc.Deferred):await restored.wait()

    async def test_getpdf_total_timeout_closes_stream_and_removes_partial(self):
        b=self.batch((1,),europePmcTimeout=.03,europePmcAttempts=1)
        class Trickle(httpx.AsyncByteStream):
            closed=False
            async def __aiter__(self):
                while True:
                    yield b'%PDF-1.4\n';await asyncio.sleep(.01)
            async def aclose(self):self.closed=True
        stream=Trickle()
        async def handler(req):return httpx.Response(200,stream=stream)
        with self.client(handler),patch.object(e,'source_s3',self.unavailable):
            await asyncio.wait_for(e.run_batch(b),1)
        self.assertTrue(stream.closed)
        self.assertEqual(self.result(b)['counts'],{'deferred':1})
        self.assertFalse(list((e.batch_dir(b)/'staging').rglob('*.pdf')))

    def test_normalization_and_settings_limits(self):
        self.assertEqual(pmc_parallel.normalize_pmcid(' pmc00123 '),'PMC123')
        for bad in ('PMC0','PMC1&x=2','PMC1.2','../1','abc',''):
            self.assertIsNone(pmc_parallel.normalize_pmcid(bad))
        self.assertEqual(e.config()['europePmcConcurrency'],4)
        for key,value in [('europePmcConcurrency',5),('europePmcAttempts',4),('europePmcTimeout',0)]:
            with self.assertRaises(ValueError):e.save_settings({key:value})


if __name__ == '__main__':
    unittest.main(verbosity=2)
