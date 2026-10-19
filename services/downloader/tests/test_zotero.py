import asyncio
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as e
import compact_io
import corpus_files as f
import zotero_local as z
import zotero_stage as stage
import zotero_worker as worker
from zotero_fixture import Fixture, attachment, parent
from test_downloads import pdf
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[3]


class Rules(unittest.TestCase):
    def test_all_snapshot_aliases_exact_and_normalized(self):
        import hashlib
        # Preserve all approved v1 entries; v2 adds only the explicitly requested title.
        baseline=[r for r in z.RULES['entries'] if r['id']!='generic_pdf_filename']
        self.assertEqual(hashlib.sha256(json.dumps(baseline,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                         '7d8063de7935661ed29fdf5636316c322e953dbb4b3935b0fabbe68d788d8f63')
        for rule in z.RULES['entries']:
            for alias in rule['aliases']:
                for value in [alias, '  '+alias.swapcase().replace(' ', ' \t ')+'  ']:
                    with self.subTest(value=value):
                        self.assertEqual(z.attachment_rule(attachment(title=value)['data']), rule)
        self.assertEqual(z.attachment_rule(attachment(title='ＰＤＦ')['data'])['id'], 'generic_pdf')
        for name in ['unknown.pdf', 'Main Article', 'Full Text PDF (unknown)', 'Prefix Full Text', 'PDF version', 'Supplementary PDF', 'Table of Contents PDF']:
            self.assertIsNone(z.attachment_rule(attachment(title=name)['data']))
    def test_link_mode_url_pdf_and_parent_url_never_substitutes(self):
        for extra in [{'linkMode':'imported_file'}, {'linkMode':'linked_file'}, {'linkMode':'linked_url'},
                      {'url':''}, {'url':'file:///tmp/a.pdf'}, {'contentType':'text/html'}, {'deleted':1}, {'url':'https://host:bad/'}]:
            self.assertIsNone(z.attachment_rule(attachment(**extra)['data']), extra)
    def test_negative_boundaries_without_false_positives(self):
        for name in ['Supplementary Information.pdf', 'Supporting_Information.pdf', 'Table-of-Contents.pdf', '补充信息.pdf', 'main-supplement.pdf', 'TOC.pdf']:
            self.assertIsNone(z.attachment_rule(attachment(filename=name)['data']), name)
        for path in ['/supplementary/main.pdf', '/a_mmc1.pdf', '/a_MOESM2_ESM.pdf', '/supp1.pdf', '/Table%20of%20Contents.pdf']:
            self.assertIsNone(z.attachment_rule(attachment(url='https://host'+path)['data']), path)
        for path in ['/data/main.pdf', '/table.pdf', '/figure.pdf', '/support.pdf', '/s1.pdf', '/appendix.pdf', '/supplementation.pdf']:
            self.assertIsNotNone(z.attachment_rule(attachment(url='https://supplement.example'+path+'?supplementary=1')['data']), path)
    def test_doi_wrappers_and_legal_punctuation(self):
        for v in [' DOI: 10.1234/Ab(C);1 ', 'https://doi.org/10.1234/Ab(C);1', 'http://dx.doi.org/10.1234/Ab(C);1']:
            self.assertEqual(z.normalize_doi(v), '10.1234/ab(c);1')
        self.assertNotEqual(z.normalize_doi('10.1234/a.'), z.normalize_doi('10.1234/a'))
    def test_addresses_loopback_only_and_no_duplicate_api(self):
        self.assertEqual(z.api_address('localhost:23119/api/api/'), 'http://127.0.0.1:23119/api/')
        self.assertEqual(z.api_address('http://[::1]:23119/'), 'http://[::1]:23119/api/')
        self.assertEqual(z.api_address(''), '')
        for value in ['https://zotero.org', '127.0.0.1.evil.test', 'http://127.0.0.1@evil.test', 'http://192.168.1.1', 'http://localhost/api/users/0', 'http://localhost/?secret=x']:
            with self.assertRaises(ValueError, msg=value):z.api_address(value)
    def test_file_url_decodes_once_and_rejects_remote(self):
        prefix='file:///C:/tmp/' if os.name=='nt' else 'file:///tmp/'
        expected=Path('C:/tmp/中 文%%20.pdf') if os.name=='nt' else Path('/tmp/中 文%%20.pdf')
        self.assertEqual(z.file_path(prefix+'%E4%B8%AD%20%E6%96%87%25%2520.pdf'),expected)
        for v in ['https://host/a.pdf', 'file://otherhost/a.pdf', 'file:relative.pdf']:
            with self.assertRaises(ValueError):z.file_path(v)
    def test_rank_priority_bytes_random_only_ties_and_persisted_choice(self):
        def c(key,priority,size):return {'key':key,'rule':{'priority':priority},'stat':[0,0,size]}
        values=[c('low',400,900),c('small',200,100),c('big',200,200)]
        self.assertEqual([v['key'] for v in z.rank(values)], ['big','small','low'])
        values=[c('a',200,10),c('b',200,10)]
        with patch.object(z.random.SystemRandom, 'shuffle', side_effect=lambda v:v.reverse()) as shuffle:
            self.assertEqual(z.rank(values)[0]['key'],'b');shuffle.assert_called_once()
        self.assertEqual(z.rank(values, 'a')[0]['key'], 'a')
    def test_pdf_dot_pdf_is_exact_title_only_and_lowest_priority(self):
        rule=z.attachment_rule(attachment(title='  pDf.PdF  ')['data'])
        self.assertEqual(rule,{'id':'generic_pdf_filename','priority':600,'aliases':['PDF.pdf'],'kind':'unspecified-pdf'})
        self.assertEqual(z.RULES['version'],'zotero-pdf-whitelist-v2')
        self.assertTrue(all(r['priority']<rule['priority'] for r in z.RULES['entries'] if r['id']!=rule['id']))
        for title in ['unknown','paper.pdf','PDF (1).pdf','PDF.pdf.backup','Full Text PDF.pdf']:
            self.assertIsNone(z.attachment_rule(attachment(title=title,filename='PDF.pdf')['data']))
        for extra in [{'linkMode':'imported_file'},{'url':''},{'filename':'supplement.pdf'},{'url':'https://host/mmc1.pdf'}]:
            self.assertIsNone(z.attachment_rule(attachment(title='PDF.pdf',**extra)['data']))


class ZoteroFixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old=e.ROOT,e.PROJECT
        self.tmp=tempfile.TemporaryDirectory(prefix='zotero-unit-',dir=ROOT/'tmp')
        e.ROOT,e.PROJECT=Path(self.tmp.name),'p'
        self.base=f.base(e)
        self.fixture=Fixture()
        self.source=e.ROOT/'来源 空格%20.pdf';self.source.write_bytes(pdf());self.fixture.paths['ATTACH01']=self.source
        self.xml(['1','2'])
        self.cfg={**e.DEFAULTS,'fastOa':False,'mirrors':[],'zoteroAddress':self.fixture.address}
        with e.db(system=True) as db:db.execute("INSERT OR REPLACE INTO settings VALUES('config',?)",(json.dumps(self.cfg),))
    def tearDown(self):
        self.fixture.close();e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
    def xml(self,ids):
        e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>Test {p}</ArticleTitle></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/test</ArticleId></ArticleIdList></PubmedData></PubmedArticle>' for p in ids)+'</PubmedArticleSet>')
    def batch(self,ids=('1',),mode=None):
        with patch.object(e,'launch'):out=e.create({'project':'p','mode':mode,'papers':[{'pmid':p,'doi':'10.1234/test','title':'Fixture'} for p in ids]})
        return e.one('SELECT * FROM batches WHERE id=?',(out['id'],))
    async def run_batch(self,ids=('1',)):
        b=self.batch(ids);await e.run_batch(b)
        self.assertEqual(e.one('SELECT state FROM batches WHERE id=?',(b['id'],))['state'],'done')
        return b


class ZoteroTests(ZoteroFixture):
    async def test_standalone_import_only_runs_zotero_and_reuses_pdfs(self):
        with e.db(system=True) as db:db.execute("UPDATE settings SET data=? WHERE key='config'",(json.dumps({**self.cfg,'fastOa':True,'enhanced':True}),))
        b=self.batch(mode='zotero')
        self.assertEqual(json.loads(b['config'])['downloadMode'],'zotero')
        with patch.object(e.pmc_parallel,'run',new_callable=AsyncMock) as pmc, patch.object(e,'source_unpaywall',new_callable=AsyncMock) as oa, patch.object(e,'source_scihub',new_callable=AsyncMock) as sci, patch.object(e,'load_sources') as sources, patch.object(e,'bloom_info') as bloom:
            await e.run_batch(b)
            for mock in (pmc,oa,sci,sources,bloom):mock.assert_not_called()
        self.assertEqual(e.one('SELECT state FROM batches WHERE id=?',(b['id'],))['state'],'done')
        self.assertEqual(json.loads(e.one('SELECT data FROM assets')['data'])['source'],'Zotero')
        self.assertEqual({r['stage'] for r in e.rows('SELECT stage FROM attempts WHERE batch=?',(b['id'],))},{'zotero'})
        self.fixture.calls.clear()
        await e.run_batch(self.batch(mode='zotero'))
        self.assertEqual(self.fixture.calls,[])
    async def test_standalone_failure_retry_preserves_mode(self):
        self.fixture.children['PARENT01']=[]
        marker=self.base/'metadata/pdf-cleared.json';e.write_json(marker,{'time':1})
        b=self.batch(mode='zotero');await e.run_batch(b)
        self.assertTrue(marker.exists())
        row=e.one('SELECT state,error FROM items WHERE batch=?',(b['id'],))
        self.assertEqual(row['state'],'failed');self.assertTrue(row['error'])
        with patch.object(e,'launch'):
            e.control({'project':'p','id':b['id'],'command':'retry'})
        self.assertEqual(json.loads(e.one('SELECT config FROM batches WHERE id=?',(b['id'],))['config'])['downloadMode'],'zotero')
    async def test_pdf_dot_pdf_fallback_after_higher_priority_unusable(self):
        self.fixture.children['PARENT01']=[attachment('ATTACH01',title='Preprint PDF'),attachment('ATTACH02',title='PDF.pdf')]
        larger=e.ROOT/'large.pdf';larger.write_bytes(pdf()+b'\n%padding'*100)
        self.fixture.paths['ATTACH02']=larger
        await self.run_batch()
        self.assertEqual(json.loads(e.one('SELECT data FROM assets')['data'])['attachmentKey'],'ATTACH01')
        (self.base/'pdf/1.pdf').unlink();self.source.write_bytes(b'broken PDF')
        await self.run_batch()
        info=json.loads(e.one('SELECT data FROM assets')['data'])
        self.assertEqual(info['attachmentKey'],'ATTACH02')
        self.assertEqual(info['ruleVersion'],'zotero-pdf-whitelist-v2')
        self.assertEqual(info['ruleId'],'generic_pdf_filename')
        self.assertEqual(info['manuscriptKind'],'unspecified-pdf')
        self.assertEqual((self.base/'pdf/1.pdf').read_bytes(),larger.read_bytes())
    async def test_duplicate_parent_pagination_exact_doi_and_global_best(self):
        self.fixture.page_size=1
        self.fixture.parents=[parent(doi='10.1234/unrelated'),parent('PARENT02','https://doi.org/10.1234/TEST'),parent('PARENT03',deleted=1),parent('PARENT04')]
        self.fixture.children['PARENT02']=[attachment('ATTACH02','PARENT02', title='PDF')]
        self.fixture.children['PARENT04']=[attachment('ATTACH04','PARENT04', title='PubMed Central Full Text PDF')]
        self.fixture.paths.update(ATTACH02=self.source,ATTACH04=self.source)
        b=await self.run_batch()
        info=json.loads(e.one('SELECT data FROM assets')['data'])
        self.assertEqual(info['attachmentKey'],'ATTACH04');self.assertEqual(info['parentKey'],'PARENT04')
        self.assertEqual(info['manuscriptKind'],'fulltext');self.assertEqual(info['doi'],'10.1234/test')
        self.assertFalse(any('/PARENT01/children' in path or '/PARENT03/children' in path for path,q in self.fixture.calls))
        text=compact_io.read_text((e.batch_dir(b)/'download_report.txt'));self.assertIn('ATTACH04',text);self.assertNotIn('PRIVATE',text)
        self.assertEqual((self.base/'literature_without_pdf.txt').read_text(),'2\n')
        self.assertEqual((e.batch_dir(b)/'literature_without_pdf.txt').read_text(),'')
        self.assertEqual(e.progress(b['id'],'1')['zotero']['attachmentKey'],'ATTACH04')
        self.assertFalse(list((e.batch_dir(b)/'staging').rglob('*.pdf')))
    async def test_incomplete_pages_rejected_even_when_first_has_match(self):
        self.fixture.page_size=1;self.fixture.page_failure=True
        self.fixture.parents=[parent(),parent('PARENT02')]
        await self.run_batch();self.assertFalse((self.base/'pdf/1.pdf').exists())
    async def test_unknown_title_unique_pdf_rejected(self):
        self.fixture.children['PARENT01']=[attachment(title='Unknown Full Text PDF')]
        await self.run_batch();self.assertFalse((self.base/'pdf/1.pdf').exists())
        self.assertFalse(any('/file/' in path for path,q in self.fixture.calls))
    async def test_bad_and_encrypted_pdf_fallback_and_actual_size(self):
        bad=e.ROOT/'broken.pdf';bad.write_bytes(b'%PDF-broken'+b'0'*2000)
        writer=PdfWriter();writer.add_blank_page(width=10,height=10);writer.encrypt('secret');locked=e.ROOT/'locked.pdf';writer.write(locked)
        self.fixture.children['PARENT01']=[attachment('ATTACH00'),attachment('ATTACH01'),attachment('ATTACH02',title='PDF'),attachment('ATTACH03',title='PDF',filesize=999999)]
        larger=e.ROOT/'larger.pdf';larger.write_bytes(pdf()+b'\n%padding'*10)
        self.fixture.paths.update(ATTACH00=bad,ATTACH01=locked,ATTACH02=larger,ATTACH03=self.source)
        await self.run_batch();info=json.loads(e.one('SELECT data FROM assets')['data'])
        self.assertEqual(info['attachmentKey'],'ATTACH02');self.assertEqual(len(info['rejectedCandidates']),2)
    async def test_nonexistent_disappeared_nonpdf_and_empty_files(self):
        self.source.write_bytes(b'')
        self.fixture.children['PARENT01'] += [attachment('ATTACH02'),attachment('ATTACH03')]
        self.fixture.paths['ATTACH03']=e.ROOT/'absent.pdf'
        await self.run_batch();self.assertFalse((self.base/'pdf/1.pdf').exists())
    async def test_service_errors_probe_once_and_preserve_failure(self):
        for mode in ['403','404','501','bad-json','redirect','disconnect','oversize']:
            with self.subTest(mode=mode):
                self.fixture.mode=mode;self.fixture.calls.clear()
                b=await self.run_batch(('1','2'))
                self.assertEqual(len(self.fixture.calls),1)
                self.assertEqual({i['state'] for i in e.rows('SELECT state FROM items WHERE batch=?',(b['id'],))},{'failed'})
                self.assertEqual((self.base/'literature_without_pdf.txt').read_text(),'1\n2\n')
    async def test_refused_and_slow_continuous_response_have_hard_bound(self):
        self.fixture.mode='slow'
        started=time.monotonic();await self.run_batch(('1','2'));self.assertLess(time.monotonic()-started,3.5)
        self.assertEqual(len(self.fixture.calls),1)
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        with e.db(system=True) as db:db.execute("UPDATE settings SET data=? WHERE key='config'",(json.dumps({**self.cfg,'zoteroAddress':f'127.0.0.1:{port}'}),))
        started=time.monotonic();await self.run_batch();self.assertLess(time.monotonic()-started,3)
    async def test_cancel_query_preserves_state_cleans_files(self):
        def pause(path,q):
            if 'q' in q:time.sleep(3)
        self.fixture.pause=pause;b=self.batch();task=asyncio.create_task(e.monitored(b))
        for _ in range(100):
            if any('q' in q for path,q in self.fixture.calls):break
            await asyncio.sleep(.02)
        e.execute("UPDATE batches SET control='cancel' WHERE id=?",(b['id'],));await asyncio.wait_for(task,2)
        self.assertEqual(e.one('SELECT state FROM batches')['state'],'cancelled')
        self.assertEqual(e.one('SELECT state FROM items')['state'],'cancelled')
        self.assertFalse((self.base/'pdf/1.pdf').exists())
        self.assertEqual(e.one("SELECT outcome FROM attempts WHERE stage='zotero'")['outcome'],'interrupted')
    async def test_total_budget_and_no_permanent_running(self):
        self.fixture.pause=lambda path,q:time.sleep(2) if 'q' in q else None
        with patch.object(z,'STAGE_SECONDS',.6):
            start=time.monotonic();b=await self.run_batch(tuple(str(x) for x in range(1,12)))
        self.assertLess(time.monotonic()-start,2)
        self.assertFalse(e.rows("SELECT * FROM items WHERE state='running'"))
        self.assertEqual(e.one("SELECT state FROM stage_runs WHERE stage='zotero'")['state'],'timeout')
        self.assertTrue(all(a['outcome']=='skipped' for a in e.rows("SELECT outcome FROM attempts WHERE stage='zotero'")))
    async def test_no_remaining_doi_or_valid_pdf_does_not_probe(self):
        self.source.replace(self.base/'existing.pdf')
        e.atomic(self.base/'pdf/1.pdf',pdf())
        await self.run_batch();self.assertEqual(self.fixture.calls,[])
        with patch.object(e,'launch'):out=e.create({'project':'p','papers':[{'pmid':'2','title':'No DOI'}]})
        await e.run_batch(e.one('SELECT * FROM batches WHERE id=?',(out['id'],)))
        self.assertEqual(self.fixture.calls,[])
    async def test_lifecycle_changed_before_publication(self):
        b=self.batch();e.execute("UPDATE batches SET state='running'")
        target=e.batch_dir(b)/'staging/1/zotero.pdf';target.parent.mkdir(parents=True)
        original=z.copy_checked
        def copy(*args):
            result=original(*args);self.xml(['2']);return result
        with patch.object(z,'copy_checked',copy):
            with self.assertRaises(ValueError):await worker.run({'mode':'doi','root':str(e.ROOT),'batch':b,'paper':{'pmid':'1'},'target':str(target),'address':self.fixture.address,'deadline':time.monotonic()+15})
        self.assertFalse((self.base/'pdf/1.pdf').exists())
    async def test_new_valid_project_pdf_is_not_overwritten(self):
        b=self.batch();e.execute("UPDATE batches SET state='running'")
        target=e.batch_dir(b)/'staging/1/zotero.pdf';target.parent.mkdir(parents=True)
        content=pdf()+b'\n%external';original=z.copy_checked
        def copy(*args):
            result=original(*args);e.atomic(self.base/'pdf/1.pdf',content);return result
        with patch.object(z,'copy_checked',copy):
            with self.assertRaises(ValueError):await worker.run({'mode':'doi','root':str(e.ROOT),'batch':b,'paper':{'pmid':'1'},'target':str(target),'address':self.fixture.address,'deadline':time.monotonic()+15})
        self.assertEqual((self.base/'pdf/1.pdf').read_bytes(),content)
    async def test_copy_failure_and_source_change_fallback(self):
        b=self.batch();e.execute("UPDATE batches SET state='running'")
        target=e.batch_dir(b)/'staging/1/zotero.pdf';target.parent.mkdir(parents=True)
        self.fixture.children['PARENT01']=[attachment('ATTACH01'),attachment('ATTACH02',title='PDF')];self.fixture.paths['ATTACH02']=self.source
        original=z.copy_checked
        def copy(candidate,*args):
            if candidate['key']=='ATTACH01':raise PermissionError('denied')
            return original(candidate,*args)
        with patch.object(z,'copy_checked',copy),patch.object(e,'validate_pdf',wraps=e.validate_pdf) as validate:
            result=await worker.run({'mode':'doi','root':str(e.ROOT),'batch':b,'paper':{'pmid':'1'},'target':str(target),'address':self.fixture.address,'deadline':time.monotonic()+15})
        self.assertEqual(result['attachmentKey'],'ATTACH02');self.assertEqual(validate.call_count,1)
        candidate={'path':self.source,'stat':z.fingerprint(self.source)};self.source.write_bytes(pdf()+b'changed')
        with self.assertRaises(ValueError):z.copy_checked(candidate,e.ROOT/'copy.pdf',e.validate_pdf)
    async def test_standard_and_enhanced_stage_order(self):
        for enhanced in (False,True):
            with e.db(system=True) as db:db.execute("UPDATE settings SET data=? WHERE key='config'",(json.dumps({**self.cfg,'enhanced':enhanced,'fastOa':True}),))
            async def s3(*a):return None,'no PDF'
            async def unpaywall(*a):raise TimeoutError()
            # No PMCID: enhanced stages are entered but perform no external calls.
            with patch.object(e,'source_s3',s3),patch.object(e,'source_unpaywall',unpaywall):b=await self.run_batch()
            order=[r['stage'] for r in e.rows('SELECT stage FROM stage_runs WHERE batch=? ORDER BY id',(b['id'],))]
            self.assertEqual(order[-1],'zotero')
            if enhanced:self.assertEqual(order,[stage for stage in e.STAGES if stage not in ('pmc_s3','europe_pmc_getpdf')])
            (self.base/'pdf/1.pdf').unlink()

class TerminationTests(ZoteroFixture):
    async def helper_scenario(self, hook, *, cancel=False, locked=False):
        helper=e.ROOT/'helper_fixture.py'
        marker=e.ROOT/'entered';pidfile=e.ROOT/'helper.pid'
        helper.write_text("import sys,json,asyncio,time,os\nfrom pathlib import Path\n"
            +f"sys.path.insert(0,{str(ROOT/'services/downloader')!r})\nimport zotero_worker as w\nimport zotero_local as z\nimport engine as e\n"
            +"req=json.load(sys.stdin)\n"
            +"if req['mode']=='doi':\n"
            +f" Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
            +hook+"\n"
            +"try: result=asyncio.run(w.run(req))\nexcept Exception as ex: result={'outcome':'skipped','reason':type(ex).__name__}\n"
            +"print(json.dumps(result))\n")
        b=self.batch();e.execute("UPDATE batches SET state='running'")
        lock=None
        if locked:
            lock=f.lock(e);lock.__enter__()
        try:
            with patch.object(stage,'HELPER',helper),patch.object(z,'DOI_SECONDS',.7):
                task=asyncio.create_task(stage.run(e,b,self.cfg))
                for _ in range(100):
                    if marker.exists() or (locked and pidfile.exists()):break
                    await asyncio.sleep(.01)
                if cancel:
                    e.execute("UPDATE batches SET control='cancel'")
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,2)
                else:await asyncio.wait_for(task,3)
        finally:
            if lock:lock.__exit__(None,None,None)
        if pidfile.exists():self.assertFalse(e.process_alive(int(pidfile.read_text())))
        self.assertFalse((self.base/'pdf/1.pdf').exists())
        self.assertFalse(list((e.batch_dir(b)/'staging').rglob('*.pdf')))
        self.assertFalse(list((e.batch_dir(b)/'staging').rglob('*.tmp')))
    async def test_parser_hang_is_killed_and_reaped(self):
        marker=e.ROOT/'entered'
        await self.helper_scenario(" def hang(*a,**k):\n  Path("+repr(str(marker))+").write_text('parse');time.sleep(30)\n e.validate_pdf=hang")
    async def test_cancel_during_parse(self):
        marker=e.ROOT/'entered'
        await self.helper_scenario(" def hang(*a,**k):\n  Path("+repr(str(marker))+").write_text('parse');time.sleep(30)\n e.validate_pdf=hang",cancel=True)
    async def test_cancel_during_copy_cleans_partial_file(self):
        marker=e.ROOT/'entered'
        await self.helper_scenario(" def hang(c,target,*a):\n  target.write_bytes(b'%PDF-partial');Path("+repr(str(marker))+").write_text('copy');time.sleep(30)\n z.copy_checked=hang",cancel=True)
    async def test_article_lock_wait_is_bounded(self):
        await self.helper_scenario(' pass',locked=True)


class AdditionalTests(ZoteroFixture):
    async def test_service_disappears_stops_remaining_queries_and_preserves_deferred(self):
        self.xml([str(p) for p in range(1,8)])
        def vanish(path,q):
            if 'q' in q:self.fixture.mode='disconnect'
        self.fixture.pause=vanish
        async def unavailable(*a):return None,'network deferred','deferred'
        with patch.object(e,'source_scihub',unavailable):b=await self.run_batch(tuple(str(p) for p in range(1,8)))
        self.assertLessEqual(len(self.fixture.calls),3)  # one probe, at most two active workers
        self.assertEqual({r['state'] for r in e.rows('SELECT state FROM items')},{'deferred'})
    async def test_cancel_not_swallowed_when_final_logging_fails(self):
        self.fixture.pause=lambda path,q:time.sleep(2) if 'q' in q else None
        b=self.batch();task=asyncio.create_task(e.monitored(b))
        for _ in range(100):
            if any('q' in q for path,q in self.fixture.calls):break
            await asyncio.sleep(.02)
        with patch.object(stage,'record_many',side_effect=OSError('diagnostic failure')):
            e.execute("UPDATE batches SET control='cancel'")
            await asyncio.wait_for(task,2)
        self.assertEqual(e.one('SELECT state FROM batches')['state'],'cancelled')
        self.assertEqual(e.one('SELECT state FROM items')['state'],'cancelled')
    async def test_epoch_changed_or_validated_staging_changed_never_publishes(self):
        import artifact_state
        for mutation in ['epoch','staging']:
            with self.subTest(mutation=mutation):
                if e.rows('SELECT * FROM batches'):e.execute("UPDATE batches SET state='done'")
                b=self.batch();e.execute("UPDATE batches SET state='running' WHERE id=?",(b['id'],))
                target=e.batch_dir(b)/'staging/1/zotero.pdf';target.parent.mkdir(parents=True)
                original=z.copy_checked
                def change(*args):
                    result=original(*args)
                    if mutation=='staging':target.write_bytes(pdf()+b'changed')
                    else:
                        membership=artifact_state.membership(e);membership.setdefault('epochs',{})['1']=artifact_state.epoch(e,'1')+1
                        e.write_json(self.base/'metadata/corpus-membership.json',membership)
                    return result
                with patch.object(z,'copy_checked',change):
                    with self.assertRaises(ValueError):await worker.run({'mode':'doi','root':str(e.ROOT),'batch':b,'paper':{'pmid':'1'},'target':str(target),'address':self.fixture.address,'deadline':time.monotonic()+15})
                self.assertFalse((self.base/'pdf/1.pdf').exists())
    async def test_local_api_duplicate_or_excessive_pages_rejected(self):
        from unittest.mock import AsyncMock
        async with z.LocalAPI(self.fixture.address) as api:
            with patch.object(api,'page',AsyncMock(side_effect=[([parent()],2),([parent()],2)])):
                with self.assertRaises(z.Unavailable):await api.pages('users/0/items/top')
            with patch.object(api,'page',AsyncMock(return_value=([parent()],2))),patch.object(z,'MAX_PAGES',1):
                with self.assertRaises(z.Unavailable):await api.pages('users/0/items/top')
    async def test_attachment_keys_deduplicated_across_parents(self):
        self.fixture.parents=[parent(),parent('PARENT02')]
        self.fixture.children['PARENT02']=[attachment(parent_key='PARENT02')]
        await self.run_batch()
        self.assertEqual(sum(path.endswith('/ATTACH01/file/view/url') for path,q in self.fixture.calls),1)
    async def test_cancellation_during_process_creation_reaps_late_handle(self):
        created=asyncio.Event();processes=[]
        original=asyncio.create_subprocess_exec
        async def delayed(*args,**kwargs):
            process=await original(*args,**kwargs);processes.append(process);created.set()
            await asyncio.sleep(.15)
            return process
        with patch.object(asyncio,'create_subprocess_exec',delayed):
            task=asyncio.create_task(stage.helper({'mode':'probe','address':self.fixture.address},2))
            await created.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNotNone(processes[0].returncode)
        self.assertFalse(e.process_alive(processes[0].pid))
        self.assertEqual(self.fixture.calls,[])
    async def test_fast_helper_control_cannot_be_finalized_as_done(self):
        async def controlled(request, seconds):
            if request['mode']=='probe':return {'outcome':'available'}
            e.execute("UPDATE batches SET control='cancel'")
            return {'outcome':'skipped','reason':'批次已停止'}
        b=self.batch()
        with patch.object(stage,'helper',controlled):await e.run_batch(b)
        self.assertEqual(e.one('SELECT state FROM batches')['state'],'cancelled')
        self.assertEqual(e.one('SELECT state FROM items')['state'],'cancelled')
        self.assertFalse((self.base/'pdf/1.pdf').exists())
    async def test_valid_manual_pdf_appearing_after_network_is_registered(self):
        b=self.batch();e.execute("UPDATE batches SET state='running'")
        e.atomic(self.base/'pdf/1.pdf',pdf());before=(self.base/'pdf/1.pdf').read_bytes()
        target=e.batch_dir(b)/'staging/1/zotero.pdf';target.parent.mkdir(parents=True)
        result=await worker.run({'mode':'doi','root':str(e.ROOT),'batch':b,'paper':{'pmid':'1'},'target':str(target),'address':self.fixture.address,'deadline':time.monotonic()+15})
        self.assertEqual(result['outcome'],'skipped')
        self.assertEqual(e.one('SELECT state FROM items')['state'],'skipped')
        self.assertEqual(json.loads(e.one('SELECT data FROM assets')['data'])['source'],'用户提供的 PDF')
        self.assertEqual((self.base/'pdf/1.pdf').read_bytes(),before)
        self.assertEqual(self.fixture.calls,[])
    async def test_empty_address_skips_and_legacy_settings_keep_default(self):
        self.assertEqual(e.DEFAULTS['zoteroAddress'],'localhost:23119')
        self.assertEqual(e.save_settings({'zoteroAddress':''})['zoteroAddress'],'')
        await self.run_batch();self.assertEqual(self.fixture.calls,[])
        with self.assertRaises(ValueError):e.save_settings({'zoteroAddress':'https://remote.example'})

if __name__=='__main__':unittest.main(verbosity=2)
