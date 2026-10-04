import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,corpus_files as f,zotero_import as zi,zotero_local as z,library_service as library
from zotero_fixture import attachment,parent
from pdf_fixture import pdf

class API:
    version='1'
    calls=[]
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def page(self,route,params):
        return ([{'key':key,'data':{'name':name,'parentCollection':parent}} for key,name,parent in [('COLLECT1','A',False),('COLLECT2','B','COLLECT1'),('COLLECT3','C','COLLECT2'),('OUTSIDE1','Outside',False)]],4)
    async def pages(self,route):
        self.calls.append(route)
        if '/collections/' in route:
            k=route.split('/')[3]
            return {'COLLECT1':[parent()['data'],parent('MISSING1',doi='')['data']], 'COLLECT2':[parent()['data'],parent('PARENT02','https://doi.org/10.1234/B(C)')['data']], 'COLLECT3':[parent('PARENT03','10.1234/third')['data']], 'OUTSIDE1':[parent()['data'],parent('PARENT04','10.1234/outside')['data']]}[k]
        return [attachment('ATTACH01',linkMode='linked_file',url='')['data']]
    async def request(self,route):
        self.calls.append(route)
        if route.endswith('/file/view/url'):return str(self.pdf.as_uri()).encode(),{}
        return json.dumps(parent()).encode(),{}

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=e.ROOT,e.PROJECT;e.ROOT,e.PROJECT=Path(self.tmp.name),'test';self.base=f.base(e)
        e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>Paper</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
        self.api=API();self.api.calls=[];self.api.pdf=e.ROOT/'original.pdf';self.api.pdf.write_bytes(pdf())
    def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
    def test_status_rereads_under_lock_and_keeps_restarted_job_alive(self):
        import time
        from contextlib import contextmanager
        path=self.base/'metadata/zotero-job.json'
        old={'id':'race','state':'running','created':time.time()-60}
        e.write_json(path,old)
        @contextmanager
        def completed_while_acquiring(*args,**kwargs):
            e.write_json(path,{**old,'state':'completed'});yield
        with patch('storage.file_lock',completed_while_acquiring):
            self.assertEqual(zi.current_job(e)['state'],'completed')
        self.assertEqual(json.loads(path.read_text())['state'],'completed')
        e.write_json(path,{**old,'started':time.time()})
        self.assertEqual(zi.current_job(e)['state'],'running')
    def test_recursive_unique_items_and_doi(self):
        result=asyncio.run(zi.scan(self.api,'COLLECT1'))
        self.assertEqual(result['total'],4);self.assertEqual(result['withDoi'],3);self.assertEqual(result['uniqueDois'],3)
        self.assertEqual(result['items'][2]['doi'],'10.1234/b(c)');self.assertFalse(any('OUTSIDE1' in r for r in self.api.calls))
    def test_multiple_branches_and_overlapping_roots_are_deduplicated(self):
        result=asyncio.run(zi.scan(self.api,['COLLECT1','COLLECT2','COLLECT1','OUTSIDE1']))
        self.assertEqual([c['key'] for c in result['selectedCollections']],['COLLECT1','OUTSIDE1'])
        self.assertEqual(len(result['collections']),4)
        self.assertEqual(result['total'],5);self.assertEqual(result['uniqueDois'],4)
        self.assertEqual(len(self.api.calls),4);self.assertEqual(len(set(self.api.calls)),4)
        self.assertIn('2 个文件夹',result['collection']['path'])
    def test_multiple_nested_selections_do_not_include_ancestors(self):
        result=asyncio.run(zi.scan(self.api,['COLLECT2','OUTSIDE1']))
        self.assertEqual({c['key'] for c in result['collections']},{'COLLECT2','COLLECT3','OUTSIDE1'})
        self.assertFalse(any('COLLECT1' in route for route in self.api.calls))
        self.assertEqual(result['total'],4)
    def test_invalid_multiselection_is_rejected_before_item_requests(self):
        for selected in [[],None,{},['MISSING1'],['../other'],['COLLECT1',None]]:
            with self.subTest(selected=selected),self.assertRaises(ValueError):asyncio.run(zi.scan(self.api,selected))
        self.assertEqual(self.api.calls,[])
    def test_whitelist_all_link_modes_but_supplement_excluded(self):
        for mode in ['imported_file','imported_url','linked_file','linked_url']:
            self.assertIsNotNone(zi.attachment_rule(attachment(linkMode=mode,url='')['data']))
        for kwargs in [{'title':'unknown.pdf'},{'filename':'supplement.pdf'},{'url':'https://example.org/a_mmc1.pdf'},{'contentType':'text/html'}]:
            self.assertIsNone(zi.attachment_rule(attachment(**kwargs)['data']))
        self.assertIsNone(z.attachment_rule(attachment(linkMode='imported_file')['data']))
    def test_doi_validation_keeps_parentheses_rejects_query_injection(self):
        self.assertEqual(zi.valid_doi(' DOI: 10.1016/S0046-8177(81)80042-1 '),'10.1016/s0046-8177(81)80042-1')
        for value in ['','not a doi','10.1234/a" OR all[all]','10.1234/a\nother','10.1234/'] :self.assertEqual(zi.valid_doi(value),'')
    def test_scoped_pdf_import_reuses_never_changes_original(self):
        args={'pmid':'1','job':'job1','address':'localhost:23119','doi':'10.1234/test','parents':['PARENT01']}
        original=self.api.pdf.read_bytes()
        with patch.object(z,'LocalAPI',return_value=self.api):
            result=asyncio.run(zi.copy_pdf(e,args));self.assertEqual(result['state'],'imported')
            self.assertEqual(asyncio.run(zi.copy_pdf(e,args))['state'],'reused')
        self.assertEqual((self.base/'pdf/1.pdf').read_bytes(),original);self.assertEqual(self.api.pdf.read_bytes(),original)
        self.assertFalse(any('/items/top' in r for r in self.api.calls));self.assertEqual(e.one('SELECT data FROM assets WHERE pmid=?',('1',)) is not None,True)
    def test_existing_download_is_reused_without_contacting_zotero(self):
        dest=f.folder(e,'pdf')/'1.pdf';original=pdf('Existing download');dest.write_bytes(original)
        with patch.object(z,'LocalAPI',side_effect=AssertionError('Existing PDF must not contact Zotero')):
            result=asyncio.run(zi.copy_pdf(e,{'pmid':'1','job':'job1'}))
        self.assertEqual(result['state'],'reused');self.assertEqual(dest.read_bytes(),original)
    def test_full_download_skips_imported_zotero_pdf_and_preserves_provenance(self):
        args={'pmid':'1','job':'job1','address':'localhost:23119','doi':'10.1234/test','parents':['PARENT01']}
        with patch.object(z,'LocalAPI',return_value=self.api):asyncio.run(zi.copy_pdf(e,args))
        original=(self.base/'pdf/1.pdf').read_bytes()
        cfg={**e.DEFAULTS,'fastOa':False,'enhanced':False,'mirrors':[]}
        e.execute('INSERT INTO batches(id,project,created,state,snapshot,config) VALUES(?,?,?,?,?,?)',('batch1','test',0,'queued','fixture',json.dumps(cfg)))
        e.execute('INSERT INTO items(batch,pmid,state,paper) VALUES(?,?,?,?)',('batch1','1','queued',json.dumps({'pmid':'1','title':'Paper','doi':'10.1234/test'})))
        e.load_sources()
        with patch.object(e,'backfill_sources'),patch.object(e.httpx.AsyncClient,'request',side_effect=AssertionError('No network fetch needed')) as request,patch.object(z,'LocalAPI',side_effect=AssertionError('No attachment fetch needed')):
            asyncio.run(e.run_batch(e.one('SELECT * FROM batches WHERE id=?',('batch1',))))
            request.assert_not_called()
        self.assertEqual(e.one('SELECT state FROM batches WHERE id=?',('batch1',))['state'],'done')
        self.assertEqual(e.one('SELECT state FROM items WHERE batch=?',('batch1',))['state'],'skipped')
        self.assertEqual(json.loads(e.one('SELECT data FROM assets WHERE pmid=?',('1',))['data'])['source'],'Zotero')
        self.assertEqual((self.base/'pdf/1.pdf').read_bytes(),original)
    def test_cancel_and_removed_membership_do_not_publish(self):
        args={'pmid':'1','job':'job1','address':'localhost:23119','doi':'10.1234/test','parents':['PARENT01']}
        cancel=self.base/'metadata/zotero-imports/job1/cancel';e.atomic(cancel,'stop')
        with self.assertRaises(ValueError):asyncio.run(zi.copy_pdf(e,args))
        cancel.unlink();e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet/>')
        with self.assertRaises(ValueError):asyncio.run(zi.copy_pdf(e,args))
        self.assertFalse((self.base/'pdf/1.pdf').exists())
    def test_active_import_blocks_cleanup_and_download_start(self):
        import time
        e.write_json(self.base/'metadata/zotero-job.json',{'id':'job1','state':'queued','created':time.time()})
        with self.assertRaisesRegex(ValueError,'Zotero'):library.check_owner(e,{})
        with self.assertRaisesRegex(ValueError,'Zotero'):e.rpc('clear',{'project':'test','confirm':'test'})

if __name__=='__main__':unittest.main()
