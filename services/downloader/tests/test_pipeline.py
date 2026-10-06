"""Source order, real streaming cancellation and bounded fallback regression tests."""
import asyncio
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e
import compact_io
e.load_sources()
import httpx
from pypdf import PdfWriter


def pdf():
    out=io.BytesIO();w=PdfWriter();w.add_blank_page(width=100,height=100);w.write(out);return out.getvalue()


class Trickle(httpx.AsyncByteStream):
    closed=False
    async def __aiter__(self):
        for _ in range(100):
            await asyncio.sleep(.01)
            yield b'%PDF-1.4\n'
    async def aclose(self):self.closed=True


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]/'tmp')
        self.root,self.project=e.ROOT,e.PROJECT
        e.ROOT,e.PROJECT=Path(self.tmp.name),'p'
        e.save_settings({'email':'test@example.org','mirrors':[]})
    def tearDown(self):
        e.ROOT,e.PROJECT=self.root,self.project;self.tmp.cleanup()
    def batch(self,**cfg):
        with patch.object(e,'launch'):
            result=e.create({'project':'p','papers':[{'pmid':'123','doi':'10.1/test'}]})
        b=e.one('SELECT * FROM batches');settings={**json.loads(b['config']),**cfg}
        e.execute('UPDATE batches SET config=?',(json.dumps(settings),))
        return e.one('SELECT * FROM batches')
    async def unavailable(self,*args):return None,'no PDF'
    def client(self,handler):
        original=httpx.AsyncClient
        return patch.object(e.httpx,'AsyncClient',side_effect=lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    def report(self,b):return json.loads(compact_io.read_text((e.batch_dir(b)/'download_report.json')))

    async def test_s3_article_timeout_falls_through_and_is_not_reported_absent(self):
        b=self.batch(s3ArticleTimeout=.04);seen=[]
        e.execute('UPDATE items SET paper=?',(json.dumps({'pmid':'123','pmcid':'PMC123'}),))
        async def slow(*args):seen.append('s3');await asyncio.sleep(1)
        async def oa(*args):seen.append('oa');return None,'no PDF'
        with patch.object(e,'source_s3',slow),patch.object(e,'source_unpaywall',oa),patch.object(e,'source_europe_pmc_getpdf',self.unavailable):
            await asyncio.wait_for(e.run_batch(b),1)
        self.assertEqual(seen,['s3','oa'])
        r=self.report(b);self.assertEqual(r['counts'],{'deferred':1})
        self.assertEqual(r['attempts'][0]['outcome'],'deferred')
        self.assertLess(r['stages'][0]['wallSeconds'],.2)

    async def test_oa_slow_stream_has_whole_file_cap_and_closes_partial_file(self):
        b=self.batch(oaFileTimeout=.05,oaArticleTimeout=.5);stream=Trickle()
        async def handler(req):
            if 'unpaywall' in req.url.host:return httpx.Response(200,json={'best_oa_location':{'url_for_pdf':'https://publisher.test/a.pdf'}})
            return httpx.Response(200,stream=stream)
        with patch.object(e,'source_s3',self.unavailable),self.client(handler):
            await asyncio.wait_for(e.run_batch(b),1)
        r=self.report(b);a=next(x for x in r['attempts'] if x['stage']=='unpaywall')
        self.assertEqual(a['outcome'],'deferred');self.assertTrue(stream.closed)
        self.assertFalse(list((e.batch_dir(b)/'staging').rglob('*.pdf')))
        detail=a['detail'];self.assertEqual(detail['entryRequests'],1);self.assertEqual(detail['fileRequests'],1)
        file=next(x for x in detail['requests'] if x['role']=='file')
        self.assertGreater(file['bytes'],0);self.assertEqual(file['finalHost'],'publisher.test')
        self.assertLess(a['elapsed'],.25)
        self.assertEqual(r['counts'],{'deferred':1})

    async def test_oa_article_cap_includes_metadata_and_all_candidates(self):
        b=self.batch(oaFileTimeout=.2,oaArticleTimeout=.07);streams=[Trickle(),Trickle()]
        async def handler(req):
            if 'unpaywall' in req.url.host:
                await asyncio.sleep(.03)
                return httpx.Response(200,json={'oa_locations':[{'url_for_pdf':'https://p.test/a.pdf'},{'url_for_pdf':'https://p.test/b.pdf'}]})
            return httpx.Response(200,stream=streams[0])
        with patch.object(e,'source_s3',self.unavailable),self.client(handler):await asyncio.wait_for(e.run_batch(b),1)
        r=self.report(b);a=next(x for x in r['attempts'] if x['stage']=='unpaywall')
        self.assertEqual(a['outcome'],'deferred');self.assertLess(a['elapsed'],.2)
        self.assertTrue(streams[0].closed);self.assertEqual(a['detail']['fileRequests'],1)

    async def test_file_timeout_can_fall_back_to_another_oa_candidate(self):
        b=self.batch(oaFileTimeout=.04,oaArticleTimeout=.5);slow=Trickle()
        async def handler(req):
            if 'unpaywall' in req.url.host:return httpx.Response(200,json={'oa_locations':[{'url_for_pdf':'https://p.test/slow.pdf'},{'url_for_pdf':'https://p.test/fast.pdf'}]})
            return httpx.Response(200,stream=slow) if req.url.path=='/slow.pdf' else httpx.Response(200,content=pdf())
        with patch.object(e,'source_s3',self.unavailable),self.client(handler):await e.run_batch(b)
        r=self.report(b);self.assertEqual(r['counts'],{'success':1})
        a=next(x for x in r['attempts'] if x['stage']=='unpaywall');self.assertEqual(a['detail']['fileRequests'],2)
        self.assertTrue(slow.closed)

    async def test_timeout_proceeds_to_scihub_and_retired_slow_rescue_never_runs(self):
        for enhanced in (False,True):
            if enhanced:
                e.execute('DELETE FROM batches');e.execute('DELETE FROM items')
            b=self.batch(oaArticleTimeout=.03,enhanced=enhanced);seen=[]
            async def oa(client,paper,path,batch,cfg):
                seen.append('slow' if cfg.get('slowOa') else 'oa')
                if cfg.get('slowOa'):path.write_bytes(pdf());return {'source':'Unpaywall'},''
                await asyncio.sleep(1)
            async def sci(paper,path,b,cfg,stage,index,bloom,health,detail):
                seen.append(stage);return None,'no PDF','failed'
            with patch.object(e,'source_s3',self.unavailable),patch.object(e,'source_unpaywall',oa),patch.object(e,'source_scihub',sci):
                await asyncio.wait_for(e.run_batch(b),1)
            # Old batches may still carry the retired flag; it must not revive the slow OA rescue.
            self.assertEqual(seen,['scihub_bloom','oa','scihub_retry'])
            self.assertEqual(self.report(b)['counts'],{'deferred':1})

    async def test_real_s3_metadata_and_download_request_counts(self):
        b=self.batch();paper={'pmid':'123','pmcid':'PMC123','doi':'10.1/test'}
        e.execute('UPDATE items SET paper=?',(json.dumps(paper),))
        async def handler(req):
            if req.url.params.get('list-type'):return httpx.Response(200,text='<ListBucketResult><CommonPrefixes><Prefix>PMC123.1/</Prefix></CommonPrefixes><IsTruncated>false</IsTruncated></ListBucketResult>')
            if req.url.path.endswith('.json'):return httpx.Response(200,json={'pmcid':'PMC123','pmid':123,'version':1,'pdf_url':'s3://pmc-oa-opendata/PMC123.1/PMC123.1.pdf'})
            return httpx.Response(200,content=pdf())
        with self.client(handler):await e.run_batch(b)
        r=self.report(b);st=r['stages'][0]
        self.assertEqual((st['entryRequests'],st['fileRequests'],st['s3PdfFound'],st['success']),(2,1,1,1))
        self.assertGreater(st['wallSeconds'],0);self.assertEqual({run['stage'] for run in r['stageRuns']},{'pmc_parallel','pmc_s3'});self.assertGreater(r['pmcParallelWallSeconds'],0)

    def test_new_timeout_settings_validated_and_saved(self):
        cfg=e.save_settings({'oaFileTimeout':50,'oaArticleTimeout':70,'s3ArticleTimeout':80})
        self.assertEqual((cfg['oaFileTimeout'],cfg['oaArticleTimeout'],cfg['s3ArticleTimeout']),(50,70,80))
        with self.assertRaises(ValueError):e.save_settings({'oaFileTimeout':0})


if __name__=='__main__':unittest.main(verbosity=2)
