"""Regressions from the 20-article Sci-Net/source-cache experiment."""
import asyncio
import hashlib
import json
from unittest.mock import patch
import test_scihub_retry as fixtures
import compact_io
import unittest
e, s, response, pdf = fixtures.e, fixtures.s, fixtures.response, fixtures.pdf

def identity_pdf():
    import io
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(width=200,height=100)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 10 50 Td (10.1/example) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(content)
    out=io.BytesIO();writer.write(out);return out.getvalue()

class SourceCacheTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.RetryTests.setUp
    tearDown = fixtures.RetryTests.tearDown
    batch = fixtures.RetryTests.batch
    browser = fixtures.RetryTests.browser

    async def test_scinet_redirect_plain_iframe_and_persisted_source(self):
        b = self.batch()
        calls = []
        async def handler(url, **kwargs):
            calls.append(url)
            if url.endswith('.pdf'):
                return response(url, content=pdf())
            return response('https://sci-net.xyz/10.1/example', text='<div class="pdf"><iframe src="/storage/main.pdf#view=FitH"></iframe></div>')
        with self.browser(handler):
            await e.run_batch(b)
        self.assertEqual(calls, ['https://entry.test/10.1/example', 'https://sci-net.xyz/storage/main.pdf'])
        asset = json.loads(e.one('SELECT data FROM assets')['data'])
        self.assertEqual(asset['source'], 'Sci-Net')
        files, pages = e.cached_sources({'pmid':'123','doi':'10.1/example'})
        self.assertEqual(files[0]['sha256'], asset['sha256'])
        self.assertEqual(pages, ['https://sci-net.xyz/10.1/example'])

    async def test_cache_survives_clear_and_non_hit_uses_file_without_entry(self):
        b = self.batch()
        paper={'pmid':'123','doi':'10.1/example'}
        body=pdf()
        e.remember_sources(paper, {'source':'Sci-Hub','url':'https://files.test/main.pdf','sha256':hashlib.sha256(body).hexdigest()})
        e.execute("UPDATE batches SET state='done'")
        folder=e.paper_dir('p','123');folder.mkdir(parents=True,exist_ok=True);(folder/'123.pdf').write_bytes(body)
        e.clear_downloads({'project':'p','confirm':'p'})
        self.assertTrue(e.cached_sources(paper)[0])
        self.assertEqual(e.cached_sources({**paper,'doi':'10.1/wrong'}), ([],[]))
        b=self.batch()
        calls=[]
        async def handler(url, **kwargs):
            calls.append(url);return response(url,content=body)
        with self.browser(handler), patch.object(e.badr,'SciHubBloomFilter',return_value=type('Bloom',(),{'contains':lambda self,doi:False,'close':lambda self:None})()):
            await e.run_batch(b)
        self.assertEqual(calls,['https://files.test/main.pdf'])
        report=json.loads(compact_io.read_text((e.batch_dir(b)/'download_report.json')))
        self.assertEqual(report['sourceCacheSuccess'],1)
        self.assertEqual(report['bloomSummary']['hits'],0)
        self.assertEqual(report['scihubSuccessByBloom'],{'hit':0,'nonHit':1})

    async def test_changed_cache_wrong_identity_falls_back(self):
        b=self.batch()
        e.remember_sources({'pmid':'123','doi':'10.1/example'}, {'source':'Sci-Hub','url':'https://files.test/old.pdf','sha256':'different'})
        calls=[]
        async def handler(url, **kwargs):
            calls.append(url)
            if url.endswith('.pdf'):return response(url,content=pdf(blank=True) if 'old.pdf' in url else pdf())
            return response(url,text='<iframe id="pdf" src="/new.pdf"></iframe>')
        with self.browser(handler):await e.run_batch(b)
        self.assertEqual(calls,['https://files.test/old.pdf','https://entry.test/10.1/example','https://entry.test/new.pdf'])
        details=json.loads(e.one("SELECT detail FROM attempts WHERE outcome='success'")['detail'])
        self.assertEqual(details['requests'][0]['kind'],'identity_unverifiable')
        self.assertEqual(details['route'],'entry-file')

    async def test_known_page_uses_origin_entry_lock(self):
        health=s.MirrorHealth()
        self.assertIs(health.lock('entry','https://sci-net.xyz/10.1/a'),health.lock('entry','https://sci-net.xyz/10.1/b'))
        e.remember_sources({'pmid':'123','doi':'10.1/example'}, {'source':'Sci-Net','pageUrl':'https://sci-net.xyz/10.1/example'})
        b=self.batch()
        calls=[]
        async def handler(url, **kwargs):
            calls.append(url)
            return response(url,content=identity_pdf()) if url.endswith('.pdf') else response(url,text='<div class="pdf"><iframe src="/paper.pdf"></iframe></div>')
        with self.browser(handler):await e.run_batch(b)
        self.assertEqual(calls,['https://sci-net.xyz/10.1/example','https://sci-net.xyz/paper.pdf'])
        detail=json.loads(e.one("SELECT detail FROM attempts WHERE outcome='success'")['detail'])
        self.assertEqual(detail['route'],'known-page-file')

    async def test_file_concurrency_two_entry_concurrency_one(self):
        health=s.MirrorHealth();active={'entry':0,'file':0};peaks=dict(active)
        async def request(role,index):
            lock=health.lock(role,f'https://same.test/{index}')
            await lock.acquire()
            try:
                active[role]+=1;peaks[role]=max(peaks[role],active[role]);await asyncio.sleep(.01)
            finally:active[role]-=1;lock.release()
        await asyncio.gather(*(request(role,n) for role in active for n in range(6)))
        self.assertEqual(peaks,{'entry':1,'file':2})

    async def test_nonhit_cache_failure_not_eligible_for_bloom_only_retry(self):
        b=self.batch()
        e.save_progress(b['id'],'123',{'bloomHit':False})
        e.execute("INSERT INTO attempts(batch,pmid,stage,outcome,elapsed,detail) VALUES(?,?,'scihub_bloom','failed',1,'{}')",(b['id'],'123'))
        e.execute("UPDATE batches SET state='done'")
        with self.assertRaisesRegex(ValueError,'没有 Bloom 命中'):
            e.create({'project':'p','mode':'bloom_retry','papers':[{'pmid':'123','doi':'10.1/example'}]})

    async def test_manual_bloom_retry_uses_known_file(self):
        b=self.batch();e.execute("UPDATE batches SET state='done'")
        e.save_progress(b['id'],'123',{'bloomHit':True})
        body=pdf();paper={'pmid':'123','doi':'10.1/example'}
        e.remember_sources(paper,{'source':'Sci-Hub','fileUrl':'https://files.test/main.pdf','sha256':hashlib.sha256(body).hexdigest()})
        with patch.object(e,'launch'):
            new=e.create({'project':'p','mode':'bloom_retry','papers':[paper]})
        b=e.one('SELECT * FROM batches WHERE id=?',(new['id'],));calls=[]
        async def handler(url, **kwargs):
            calls.append(url);return response(url,content=body)
        with self.browser(handler):await e.run_batch(b)
        self.assertEqual(calls,['https://files.test/main.pdf'])
        self.assertEqual(e.progress(b['id'],'123')['retryStatus'],'success')

    async def test_signed_file_url_is_not_cached_without_query(self):
        b=self.batch()
        async def handler(url, **kwargs):
            if '/main.pdf' in url:return response(url,content=pdf())
            return response(url,text='<iframe id="pdf" src="https://files.test/main.pdf?signature=private"></iframe>')
        with self.browser(handler):await e.run_batch(b)
        files,pages=e.cached_sources({'pmid':'123','doi':'10.1/example'})
        self.assertEqual(files,[])
        detail=json.loads(e.one("SELECT detail FROM attempts WHERE outcome='success'")['detail'])
        self.assertNotIn('private',json.dumps(detail))
