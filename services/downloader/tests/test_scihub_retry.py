import asyncio
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from email.utils import formatdate
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as e
import compact_io
import scihub_retry as s
import scihub_browser
e.load_sources()
from pypdf import PdfWriter


from pdf_fixture import pdf


def response(url, status=200, text='', content=None, headers=None):
    return SimpleNamespace(url=url, status_code=status, text=text,
                           content=content if content is not None else text.encode(), headers=headers or {})


class Browser:
    def __init__(self, handler):
        self.handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, **kwargs):
        return await self.handler(url, **kwargs)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3] / 'tmp')
        self.root, self.project = e.ROOT, e.PROJECT
        e.ROOT, e.PROJECT = Path(self.tmp.name), 'p'
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(s, 'FIRST_DELAY', (0, 0)))
        self.stack.enter_context(patch.object(s, 'MIRROR_COOLDOWN', (0, 0)))
        self.stack.enter_context(patch.object(e, 'bloom_info', return_value={}))
        self.stack.enter_context(patch.object(e.badr, 'SciHubBloomFilter', return_value=SimpleNamespace(contains=lambda doi: True, close=lambda: None)))
        async def unavailable(*args):
            return None, 'no PDF'
        self.stack.enter_context(patch.object(e, 'source_unpaywall', unavailable))
        self.stack.enter_context(patch.object(e, 'source_s3', unavailable))

    def tearDown(self):
        self.stack.close()
        e.ROOT, e.PROJECT = self.root, self.project
        self.tmp.cleanup()

    def batch(self, papers=None):
        e.save_settings({'mirrors': ['https://entry.test']})
        with patch.object(e, 'launch'):
            result = e.create({'project': 'p', 'papers': papers or [{'pmid': '123', 'doi': '10.1/example'}]})
        records=papers or [{'pmid':'123','doi':'10.1/example'}]
        e.atomic(e.storage.project_dir(e.ROOT,e.PROJECT)/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p["pmid"]}</PMID></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">{p.get("doi","")}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>' for p in records)+'</PubmedArticleSet>')
        return e.one('SELECT * FROM batches WHERE id=?', (result['id'],))

    def browser(self, handler):
        return patch.object(scihub_browser.BrowserPool, 'session', side_effect=lambda **kwargs: Browser(handler))

    def test_retry_after_seconds_and_dates_and_health_persistence(self):
        self.assertEqual(s.retry_after('240', 1000), 240)
        self.assertEqual(s.retry_after(formatdate(1300, usegmt=True), 1000), 300)
        self.assertEqual(s.retry_after('invalid', 1000), 0)
        saved = {}
        health = s.MirrorHealth(save=lambda k, v: saved.update({k: v}), clock=lambda: 1000, jitter=lambda *args: 20)
        health.update('entry', 'https://entry.test', 'rate_limited', 300)
        restored = s.MirrorHealth(saved, clock=lambda: 1000)
        self.assertEqual(restored.available_at('entry', 'https://entry.test'), 1300)
        self.assertEqual(restored.available_at('file', 'https://entry.test/a.pdf'), 0)

    async def test_first_502_then_supplemental_success_report_and_timings(self):
        b = self.batch()
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                return response(url, 502)
            if url.endswith('.pdf'):
                return response(url, content=pdf())
            return response(url, text='<iframe id="pdf" src="/main.pdf"></iframe>')
        with self.browser(handler):
            await e.run_batch(b)
        self.assertEqual(len(calls), 3)
        self.assertEqual(e.one('SELECT * FROM items')['state'], 'success')
        state = e.progress(b['id'], '123')
        self.assertEqual(state['retryUsed'], 1)
        self.assertEqual(state['retryStatus'], 'success')
        report = json.loads(compact_io.read_text((e.batch_dir(b) / 'download_report.json')))
        self.assertEqual(report['bloomSummary'], dict(hits=1, firstSuccess=0, retrySuccess=1, otherRecovery=0, failed=0, deferred=0, pending=0))
        detail = next(a['detail'] for a in report['attempts'] if a['stage'] == 'scihub_retry')
        self.assertEqual([r['role'] for r in detail['requests']], ['entry', 'file'])
        self.assertEqual(set(detail['timings']), {'queueSeconds', 'cooldownSeconds', 'lookupSeconds', 'downloadSeconds', 'validationSeconds'})
        self.assertGreater(detail['timings']['validationSeconds'], 0)

    async def test_pmc_s3_success_skips_both_scihub_passes(self):
        b = self.batch([{'pmid':'123','pmcid':'PMC123','doi':'10.1/example'}])
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            return response(url, text='<title>Checking your browser</title>captcha')
        async def pmc(client, paper, path, batch, cfg):
            path.write_bytes(pdf())
            return {'source': 'PMC S3'}, ''
        with self.browser(handler), patch.object(e, 'source_s3', pmc):
            await e.run_batch(b)
        self.assertEqual(len(calls), 0)
        self.assertEqual(e.one('SELECT state FROM items')['state'], 'success')
        events = (e.batch_dir(b) / 'download_events.jsonl').read_text()
        self.assertNotIn('suspected_challenge', events)
        self.assertNotIn('CAPTCHA triggered', events)
        self.assertEqual(e.rows("SELECT * FROM attempts WHERE stage='scihub_retry'"), [])

    async def test_certificate_failure_disabled_for_entire_batch(self):
        b = self.batch()
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            raise RuntimeError('curl: (60) SSL certificate problem: self signed certificate in chain')
        with self.browser(handler):
            await e.run_batch(b)
        self.assertEqual(len(calls), 1)
        state = e.progress(b['id'], '123')
        self.assertEqual(state['retryStatus'], 'deferred')
        self.assertEqual(state.get('retryUsed', 0), 0)
        self.assertIn('self signed certificate in chain', (e.batch_dir(b) / 'download_events.jsonl').read_text())

    async def test_failed_entry_does_not_block_same_host_pdf(self):
        health = s.MirrorHealth()
        health.update('entry', 'https://storage.test', 'tls_certificate')
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            return response(url, content=pdf('10.1/a')) if url.endswith('.pdf') else response(url, text='<embed type="application/pdf" src="https://storage.test/storage/main.pdf">')
        result, _, _ = await s.download('10.1/a', e.ROOT / 'x.pdf', ['https://entry.test'], health,
            lambda *a, **k: None, e.validate_pdf, session_factory=lambda **k: Browser(handler))
        self.assertIsNotNone(result)
        self.assertEqual(calls[-1], 'https://storage.test/storage/main.pdf')

    async def test_supplemental_visits_all_supplied_mirrors_without_two_entry_limit(self):
        calls, consumed = [], []
        async def handler(url, **kwargs):
            calls.append(url)
            return response(url, text='no link')
        result, _, _ = await s.download('10.1/a', e.ROOT / 'x.pdf', ['https://a.test', 'https://b.test', 'https://c.test'],
            s.MirrorHealth(), lambda *a, **k: None, e.validate_pdf, supplemental=True, used=1,
            consume=lambda: consumed.append(1), deadline=time.time()+10, session_factory=lambda **k: Browser(handler))
        self.assertIsNone(result)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(consumed), 3)

    async def test_429_long_retry_after_deferred_without_hammering(self):
        b = self.batch()
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            return response(url, 429, headers={'Retry-After': '600'})
        with self.browser(handler):
            await asyncio.wait_for(e.run_batch(b), 2)
        self.assertEqual(len(calls), 1)
        self.assertGreater(json.loads(e.one('SELECT data FROM mirror_health')['data'])['nextAttemptAt'], time.time()+590)
        self.assertEqual(e.one('SELECT * FROM items')['state'], 'deferred')
        self.assertEqual(e.progress(b['id'], '123').get('retryUsed',0),0)

    async def test_pause_wait_resume_does_not_replay_first_round(self):
        b = self.batch()
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            return response(url, text='captcha') if len(calls) == 1 else response(url, content=pdf())
        with self.browser(handler), patch.object(s, 'FIRST_DELAY', (1, 1)):
            task = asyncio.create_task(e.run_batch(b))
            for _ in range(100):
                await asyncio.sleep(.005)
                if e.one('SELECT * FROM items')['stage'] == 'scihub_retry':
                    break
            task.cancel()
            await task
            self.assertEqual(e.one('SELECT * FROM batches')['state'], 'paused')
            self.assertEqual(len(calls), 1)
            self.assertIn('scihub_bloom', e.progress(b['id'], '123')['completedStages'])
            with patch.object(e, 'launch'):
                e.control({'project': 'p', 'id': b['id'], 'command': 'resume'})
            await e.run_batch(e.one('SELECT * FROM batches'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(e.one('SELECT * FROM items')['state'], 'success')
        self.assertEqual(e.progress(b['id'], '123')['retryUsed'], 1)

    async def test_interrupted_request_still_consumes_budget_after_resume(self):
        b = self.batch()
        calls, begun = [], asyncio.Event()
        async def handler(url, **kwargs):
            calls.append(url)
            if len(calls) == 2:
                begun.set()
                await asyncio.sleep(20)
            return response(url, text='no link')
        with self.browser(handler):
            task = asyncio.create_task(e.run_batch(b))
            await asyncio.wait_for(begun.wait(), 2)
            task.cancel()
            await task
            self.assertEqual(e.progress(b['id'], '123')['retryUsed'], 1)
            with patch.object(e, 'launch'):
                e.control({'project': 'p', 'id': b['id'], 'command': 'resume'})
            await e.run_batch(e.one('SELECT * FROM batches'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(e.progress(b['id'], '123')['retryUsed'], 1)
        self.assertEqual(e.one('SELECT * FROM items')['state'], 'deferred')

    async def test_budget_cancels_slow_request(self):
        b = self.batch()
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            if len(calls) > 1:
                await asyncio.sleep(10)
            return response(url, text='no link')
        with self.browser(handler), patch.object(s, 'RETRY_BUDGET', .05):
            await asyncio.wait_for(e.run_batch(b), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(e.one('SELECT * FROM items')['state'], 'deferred')
        self.assertEqual(e.progress(b['id'], '123')['retryUsed'], 1)

    def test_manual_recovery_filters_current_corpus_and_valid_local_pdf(self):
        b = self.batch([{'pmid': p, 'doi': '10.1/'+p} for p in ('123','124','125')])
        for p in ('123','124','125'):
            e.execute("INSERT INTO attempts(batch,pmid,stage,outcome,elapsed,detail) VALUES(?,?,'scihub_bloom','failed',0,'{}')", (b['id'],p))
        e.execute("UPDATE items SET state='failed'")
        e.execute("UPDATE batches SET state='done'")
        dest=e.paper_dir('p','124')/'124.pdf';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(pdf())
        # 125 was removed from the current corpus; 126 was never Bloom-hit/attempted.
        with patch.object(e, 'launch'):
            result=e.create({'project':'p','mode':'bloom_retry','papers':[{'pmid':p,'doi':'10.1/'+p} for p in ('123','124','126')]})
        self.assertEqual(result['count'],1)
        self.assertEqual(e.rows('SELECT pmid FROM items WHERE batch=?',(result['id'],)),[{'pmid':'123'}])
        self.assertTrue(e.progress(result['id'],'123')['manualRecovery'])

    async def test_38_article_regression_bloom_group_finishes_before_nonhits(self):
        papers=[{'pmid':str(p),'doi':'10.1/'+str(p)} for p in range(100,138)]
        b=self.batch(papers)
        cfg=json.loads(b['config']);cfg['mirrors']=['https://a.test','https://b.test']
        e.execute('UPDATE batches SET config=? WHERE id=?',(json.dumps(cfg),b['id']));b=e.one('SELECT * FROM batches')
        calls=[]
        async def handler(url,**kwargs):
            p=url.rsplit('/',1)[-1]
            stage=e.one('SELECT stage FROM items WHERE pmid=?',(p,))['stage']
            calls.append((stage,p))
            await asyncio.sleep(.001)
            if stage=='scihub_bloom':return response(url,text='captcha')
            return response(url,content=pdf('10.1/'+p)) if int(p)<117 else response(url,403)
        bloom=SimpleNamespace(contains=lambda doi:int(doi.rsplit('/',1)[-1])<117,close=lambda:None)
        with self.browser(handler),patch.object(e.badr,'SciHubBloomFilter',return_value=bloom),patch.object(s,'FIRST_DELAY',(.08,.08)):
            await e.run_batch(b)
        first=[p for stage,p in calls if stage=='scihub_bloom']
        second=[p for stage,p in calls if stage=='scihub_retry']
        self.assertEqual(set(first),{str(p) for p in range(100,117)})
        self.assertEqual(len(first),34)  # Both mirrors actually tried for all 17 hits.
        self.assertEqual(set(second[:17]),{str(p) for p in range(100,117)})
        self.assertTrue(all(int(p)>=117 for p in second[17:]))
        self.assertEqual(len(second),17+21*2)
        report=json.loads(compact_io.read_text((e.batch_dir(b)/'download_report.json')))
        self.assertEqual(report['bloomSummary']['retrySuccess'],17)
        self.assertEqual(report['counts']['success'],17)
        self.assertEqual(report['counts']['failed'],21)
        first_stage=next(st for st in report['stages'] if st['stage']=='scihub_bloom')
        self.assertEqual(first_stage['entryRequests'],34)
        for p in range(100,117):self.assertEqual(e.progress(b['id'],str(p))['retryUsed'],1)

    async def test_cooldown_does_not_consume_network_budget(self):
        b=self.batch();calls=[]
        async def handler(url,**kwargs):
            calls.append(url);await asyncio.sleep(.003)
            return response(url,text='captcha') if len(calls)==1 else response(url,content=pdf())
        with self.browser(handler),patch.object(s,'FIRST_DELAY',(.08,.08)),patch.object(s,'RETRY_BUDGET',.03):
            await e.run_batch(b)
        state=e.progress(b['id'],'123')
        self.assertEqual(e.one('SELECT state FROM items')['state'],'success')
        self.assertGreater(state['retryWaitSeconds'],.05)
        self.assertLess(state['retryNetworkSeconds'],.03)

    def test_only_repeated_distinct_transport_failures_cool_entire_mirror(self):
        health=s.MirrorHealth(clock=lambda:1000,jitter=lambda *args:60)
        for kind in ('forbidden','suspected_challenge'):
            for n in range(10):health.update('entry','https://a.test',kind,article=str(n))
            self.assertEqual(health.available_at('entry','https://a.test'),0)
        for _ in range(5):health.update('entry','https://a.test','temporary_server_error',article='one')
        self.assertEqual(health.available_at('entry','https://a.test'),0)
        health.update('entry','https://a.test','temporary_server_error',article='two')
        self.assertEqual(health.available_at('entry','https://a.test'),0)
        health.update('entry','https://a.test','temporary_server_error',article='three')
        self.assertEqual(health.available_at('entry','https://a.test'),1060)

    async def test_all_rate_limited_concurrent_items_are_deferred_not_fake_failures(self):
        b=self.batch([{'pmid':str(p),'doi':'10.1/'+str(p)} for p in range(100,110)])
        calls=[]
        async def handler(url,**kwargs):
            calls.append(url);await asyncio.sleep(.002)
            return response(url,429,headers={'Retry-After':'600'})
        with self.browser(handler):await asyncio.wait_for(e.run_batch(b),3)
        self.assertEqual(len(calls),1)
        report=json.loads(compact_io.read_text((e.batch_dir(b)/'download_report.json')))
        self.assertEqual(report['counts'],{'deferred':10})
        self.assertEqual(report['bloomSummary']['deferred'],10)
        retry=next(st for st in report['stages'] if st['stage']=='scihub_retry')
        self.assertEqual(retry['entryRequests'],0)
        self.assertEqual(retry['attempted'],0)
        self.assertEqual(retry['deferred'],10)
        with patch.object(e,'launch'):
            e.control({'project':'p','id':b['id'],'command':'retry'})
        self.assertEqual(len(e.rows("SELECT * FROM items WHERE state='queued'")),10)

    def test_old_article_cooldown_migrated_but_server_rate_limit_preserved(self):
        records={'entry:https://a.test':{'lastError':'suspected_challenge','nextAttemptAt':2000},
                 'entry:https://b.test':{'lastError':'rate_limited','nextAttemptAt':2000}}
        health=s.MirrorHealth(records,clock=lambda:1000)
        self.assertEqual(health.available_at('entry','https://a.test'),0)
        self.assertEqual(health.available_at('entry','https://b.test'),2000)

    async def test_first_pass_serial_per_mirror_but_parallel_across_mirrors(self):
        from collections import Counter
        from urllib.parse import urlsplit
        b=self.batch([{'pmid':str(p),'doi':'10.1/'+str(p)} for p in range(100,112)])
        cfg=json.loads(b['config']);cfg['mirrors']=['https://a.test','https://b.test','https://c.test']
        e.execute('UPDATE batches SET config=?',(json.dumps(cfg),));b=e.one('SELECT * FROM batches')
        active=Counter();peaks=Counter();first=[];total_peak=0
        async def handler(url,**kwargs):
            nonlocal total_peak
            host=urlsplit(url).hostname;p=url.rsplit('/',1)[-1]
            stage=e.one('SELECT stage FROM items WHERE pmid=?',(p,))['stage']
            active[host]+=1;peaks[host]=max(peaks[host],active[host]);total_peak=max(total_peak,sum(active.values()))
            try:
                if stage=='scihub_bloom':first.append((p,host))
                await asyncio.sleep(.015)
                return response(url,403)
            finally:active[host]-=1
        with self.browser(handler):await e.run_batch(b)
        self.assertEqual(dict(peaks),{'a.test':1,'b.test':1,'c.test':1})
        self.assertEqual(total_peak,3)
        for p in range(100,112):self.assertEqual({h for ident,h in first if ident==str(p)},{'a.test','b.test','c.test'})
        self.assertEqual(len(first),36)

    async def test_supplemental_can_succeed_on_third_mirror(self):
        b=self.batch();cfg=json.loads(b['config']);cfg['mirrors']=['https://a.test','https://b.test','https://c.test']
        e.execute('UPDATE batches SET config=?',(json.dumps(cfg),));b=e.one('SELECT * FROM batches')
        async def handler(url,**kwargs):
            retry=e.one('SELECT stage FROM items')['stage']=='scihub_retry'
            return response(url,content=pdf()) if retry and url.startswith('https://c.test') else response(url,403)
        with self.browser(handler):await e.run_batch(b)
        self.assertEqual(e.one('SELECT state FROM items')['state'],'success')
        self.assertEqual(e.progress(b['id'],'123')['retryUsed'],3)

    async def test_transient_outage_does_not_hold_batch_in_cooldown(self):
        b=self.batch([{'pmid':str(p),'doi':'10.1/'+str(p)} for p in range(100,108)])
        calls=[]
        async def handler(url,**kwargs):calls.append(url);return response(url,502)
        with self.browser(handler),patch.object(s,'MIRROR_COOLDOWN',(120,120)):
            await asyncio.wait_for(e.run_batch(b),2)
        self.assertEqual(len(calls),3)
        self.assertTrue(all(i['state']=='deferred' for i in e.rows('SELECT state FROM items')))

    async def test_entry_os_lock_shared_between_independent_project_health_objects(self):
        locks=e.ROOT/'locks';a=s.MirrorHealth(lock_dir=locks);b=s.MirrorHealth(lock_dir=locks)
        first=a.lock('entry','https://ENTRY.test/');second=b.lock('entry','https://entry.test:443')
        await first.acquire()
        task=asyncio.create_task(second.acquire())
        await asyncio.sleep(.08);self.assertFalse(task.done())
        # Another mirror remains independent even while this one is held.
        other=b.lock('entry','https://other.test');await asyncio.wait_for(other.acquire(),.1);other.release()
        first.release();await asyncio.wait_for(task,.2);second.release()

    async def test_cancel_os_lock_wait_releases_local_lock(self):
        locks=e.ROOT/'locks';a=s.MirrorHealth(lock_dir=locks);b=s.MirrorHealth(lock_dir=locks)
        first=a.lock('entry','https://a.test');second=b.lock('entry','https://a.test')
        await first.acquire();task=asyncio.create_task(second.acquire());await asyncio.sleep(.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(second.locked());first.release()
        await asyncio.wait_for(second.acquire(),.1);second.release()

    async def test_entry_lock_is_exclusive_across_processes_and_released_on_exit(self):
        directory=str(e.ROOT/'process-locks')
        code="""import asyncio,sys
sys.path.insert(0,sys.argv[1])
from scihub_retry import MirrorHealth
async def main():
 lock=MirrorHealth(lock_dir=sys.argv[2]).lock('entry','https://same.test')
 await lock.acquire()
 print('acquired',flush=True)
 await asyncio.sleep(30)
asyncio.run(main())
"""
        child=await asyncio.create_subprocess_exec(sys.executable,'-u','-c',code,str(Path(s.__file__).parent),directory,stdout=asyncio.subprocess.PIPE)
        try:
            self.assertEqual(await asyncio.wait_for(child.stdout.readline(),2),b'acquired\n')
            lock=s.MirrorHealth(lock_dir=directory).lock('entry','https://same.test')
            with self.assertRaises(TimeoutError):await asyncio.wait_for(lock.acquire(),.08)
            child.terminate();await child.wait()
            await asyncio.wait_for(lock.acquire(),.2);lock.release()
        finally:
            if child.returncode is None:child.terminate();await child.wait()


if __name__ == '__main__':
    unittest.main(verbosity=2)
