import asyncio, hashlib, io, json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import engine as e
e.load_sources()
import httpx
from pypdf import PdfWriter

def pdf():
    out=io.BytesIO();w=PdfWriter();w.add_blank_page(width=100,height=100);w.write(out);return out.getvalue()
class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=str(pathlib.Path(__file__).resolve().parents[3]/'tmp'))
        self.old=e.ROOT;e.ROOT=pathlib.Path(self.tmp.name);self.b={'id':'b','project':'p'}
        async def no_getpdf(*args):return None,'no PDF'
        adapter=patch.object(e,'source_europe_pmc_getpdf',no_getpdf);adapter.start();self.addCleanup(adapter.stop)
    def tearDown(self):e.ROOT=self.old;self.tmp.cleanup()
    def batch(self,papers=None):
        with patch.object(e,'launch'):
            r=e.create({'project':'p','snapshot':'snap','papers':papers or [{'pmid':'123','pmcid':'PMC123','title':'Test'}]})
        return e.one('SELECT * FROM batches WHERE id=?',(r['id'],))
    def test_defaults_and_validation(self):
        self.assertNotIn('enhanced',e.config())
        for v in [-1,0,31]:
            with self.assertRaises(ValueError):e.save_settings({'unpaywallConcurrency':v})
        with self.assertRaises(ValueError):e.save_settings({'email':'bad'})
        self.assertNotIn('enhanced',e.config())
    def test_bloom_is_app_managed_and_import_rpc_removed(self):
        e.save_settings({'bloom':'/tmp/other.bloom'})
        self.assertNotIn('bloom',e.config());self.assertNotIn('bloomInfo',e.get_settings())
        self.assertEqual(e.BUILTIN_BLOOM,'data/reference/download/scihub.bloom')
        with self.assertRaises(ValueError):e.download_rpc('bloom.import',{'path':'/tmp/other.bloom'})
    def test_pdf_not_html_and_checksum(self):
        p=e.ROOT/'test.pdf';p.write_bytes(b'<html>not PDF</html>')
        with self.assertRaises(ValueError):e.validate_pdf(p)
        p.write_bytes(pdf());self.assertEqual(e.validate_pdf(p)['pages'],1)
        with self.assertRaises(ValueError):e.validate_pdf(p,'0'*32)
    def test_authoritative_pdf_and_identity(self):
        meta={'pmcid':'PMC123','pmid':123,'version':2,'pdf_url':'s3://pmc-oa-opendata/PMC123.2/PMC123.2.pdf?md5=abc','media_urls':['s3://pmc-oa-opendata/PMC123.2/supplement.pdf']}
        self.assertEqual(e.s3_pdf(meta,'PMC123','123')[1],'PMC123.2/PMC123.2.pdf')
        with self.assertRaises(ValueError):e.s3_pdf(meta,'PMC123','999')
        meta['pdf_url']=None;self.assertIsNone(e.s3_pdf(meta,'PMC123','123'))
    async def test_s3_pagination_boundary(self):
        calls=[]
        async def handler(req):
            calls.append(req);self.assertEqual(req.url.params['prefix'],'PMC123.')
            token=req.url.params.get('continuation-token')
            return httpx.Response(200,text=('<ListBucketResult xmlns="urn:s3"><CommonPrefixes><Prefix>PMC123.2/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>PMC1234.1/</Prefix></CommonPrefixes><IsTruncated>true</IsTruncated><NextContinuationToken>next</NextContinuationToken></ListBucketResult>' if not token else '<ListBucketResult xmlns="urn:s3"><CommonPrefixes><Prefix>PMC123.3/</Prefix></CommonPrefixes><IsTruncated>false</IsTruncated></ListBucketResult>'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            self.assertEqual(await e.s3_versions(c,'PMC123',1),['PMC123.2','PMC123.3'])
        self.assertEqual(len(calls),2)
    async def test_s3_current_version_and_supplement(self):
        content=pdf();md5=hashlib.md5(content).hexdigest();seen=[]
        async def handler(req):
            seen.append(str(req.url));path=req.url.path
            if req.url.params.get('list-type'):return httpx.Response(200,text='<ListBucketResult><CommonPrefixes><Prefix>PMC123.1/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>PMC123.2/</Prefix></CommonPrefixes><IsTruncated>false</IsTruncated></ListBucketResult>')
            if 'idconv' in path:return httpx.Response(200,json={'records':[{'versions':[{'current':True,'pmcid':'PMC123.1'}]}]})
            if path.endswith('.json'):return httpx.Response(200,json={'pmcid':'PMC123','pmid':123,'version':1,'pdf_url':f's3://pmc-oa-opendata/PMC123.1/PMC123.1.pdf?md5={md5}','media_urls':['s3://pmc-oa-opendata/PMC123.1/huge-supplement.pdf']})
            if path.endswith('PMC123.1.pdf'):return httpx.Response(200,content=content)
            raise AssertionError(path)
        b=self.batch();path=e.ROOT/'candidate.pdf'
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            info,reason=await e.source_s3(c,{'pmid':'123','pmcid':'PMC123'},path,b,{**e.DEFAULTS,'attempts':1})
        self.assertEqual(info['version'],1);self.assertEqual(info['selectionReason'],'PMC current');self.assertTrue(path.exists());self.assertFalse(any('supplement.pdf' in u for u in seen))
    async def test_retry_503_and_html_rejection(self):
        content=pdf();calls=0
        async def handler(req):
            nonlocal calls;calls+=1
            return httpx.Response(503 if calls==1 else 200,content=b'busy' if calls==1 else content)
        b=self.batch()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            result=await e.fetch_pdf(c,'https://example.org/a.pdf',e.ROOT/'a.part',b,'123','pmc_s3',2)
            self.assertEqual(result['pages'],1);self.assertEqual(calls,2)
    def test_duplicate_batch_and_recovery_controls(self):
        b=self.batch([{'pmid':'123'},{'pmid':'123'}]);self.assertEqual(len(e.rows('SELECT * FROM items')),1)
        with patch.object(e,'launch'):
            with self.assertRaises(ValueError):self.batch()
            e.control({'project':'p','id':b['id'],'command':'pause'})
            self.assertEqual(e.one('SELECT * FROM batches')['state'],'paused')
            e.control({'project':'p','id':b['id'],'command':'resume'})
            self.assertEqual(e.one('SELECT * FROM batches')['state'],'queued')
            e.execute("UPDATE batches SET state='running'");e.execute("UPDATE items SET state='running'");e.recover()
            self.assertEqual(e.one('SELECT * FROM batches')['state'],'paused')
        report=e.batch_dir(b)/'download_report.txt';self.assertTrue(report.exists());self.assertIn('Unfinished: 1',report.read_text());self.assertIn('Final failed: 0',report.read_text())
    async def test_default_pipeline_order_no_rescue_and_existing_reuse(self):
        b=self.batch();seen=[];content=pdf()
        async def fake_s3(client,paper,path,b,cfg):seen.append('s3');path.write_bytes(content);return {'source':'PMC S3'},''
        async def fake_unpaywall(*args):seen.append('unpaywall');return None,'no PDF'
        with patch.object(e,'source_s3',fake_s3),patch.object(e,'source_unpaywall',fake_unpaywall):await e.run_batch(b)
        self.assertEqual(seen,['s3']);self.assertTrue((e.paper_dir('p','123')/'123.pdf').exists());self.assertEqual(e.one('SELECT * FROM items')['state'],'success')
        b2=self.batch();await e.run_batch(b2);self.assertEqual(e.one('SELECT * FROM items WHERE batch=?',(b2['id'],))['state'],'skipped')
    async def test_cancel_inflight_keeps_unfinished_not_failed(self):
        b=self.batch()
        async def slow(*args):await asyncio.sleep(60)
        task=asyncio.create_task(e.monitored(b))
        with patch.object(e,'source_unpaywall',slow):
            await asyncio.sleep(.15);e.execute("UPDATE batches SET control='cancel' WHERE id=?",(b['id'],));await asyncio.wait_for(task,3)
        self.assertEqual(e.one('SELECT * FROM batches')['state'],'cancelled');self.assertEqual(e.one('SELECT * FROM items')['state'],'cancelled')
        self.assertIn('Final failed: 0',(e.batch_dir(b)/'download_report.txt').read_text())
    def test_retired_enhanced_setting_cannot_enable_retry_sources(self):
        b=self.batch();e.execute("UPDATE batches SET state='done'");e.execute("UPDATE items SET state='failed'")
        e.save_settings({'enhanced':True})
        with patch.object(e,'launch'):e.control({'project':'p','id':b['id'],'command':'retry'})
        self.assertNotIn('enhanced',json.loads(e.one('SELECT * FROM batches')['config']))
    async def test_old_batch_cannot_run_retired_sources(self):
        e.save_settings({'mirrors':[]});b=self.batch();b['config']=json.dumps({**json.loads(b['config']),'enhanced':True,'bloom':'untrusted.bloom'});seen=[]
        async def unpaywall(*args):seen.append('unpaywall');return None,'no PDF'
        async def s3(*args):seen.append('s3');return None,'no PDF'
        with patch.object(e,'source_unpaywall',unpaywall),patch.object(e,'source_s3',s3):await e.run_batch(b)
        self.assertEqual(seen,['s3','unpaywall']);self.assertEqual(e.one('SELECT * FROM items')['state'],'failed')
    async def test_owner_exit_pauses_batch(self):
        b=self.batch();b['owner']=123456789
        async def slow(*args):await asyncio.sleep(60)
        with patch.object(e,'source_unpaywall',slow),patch.object(e,'process_alive',return_value=False):await asyncio.wait_for(e.monitored(b),3)
        self.assertEqual(e.one('SELECT * FROM batches')['state'],'paused')
        self.assertEqual(e.one('SELECT * FROM items')['state'],'paused')
    def test_bloom_truncation_rejected(self):
        header=json.dumps({'bit_count':8,'hash_count':1}).encode();path=e.ROOT/'index.bloom'
        import struct
        path.write_bytes(b'OPDRBF1\n'+struct.pack('>I',len(header))+header+b'\xff');self.assertTrue(e.bloom_info(path)['valid'])
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(ValueError):e.bloom_info(path)
if __name__=='__main__':unittest.main(verbosity=2)
