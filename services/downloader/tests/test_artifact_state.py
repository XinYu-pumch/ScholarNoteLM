import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,corpus_files as f,artifact_state as a,markdown_service as m,vector_chunks as c
import test_scihub_retry as fixtures

class ArtifactStateTests(unittest.TestCase):
 def setUp(self):
  self.old=(e.ROOT,e.PROJECT);self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test';self.base=f.base(e);self.xml(['1','2'])
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def xml(self,ids,title='Title'):
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>{title}</ArticleTitle><Abstract><AbstractText>'+('Abstract evidence. '*20)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for p in ids)+'</PubmedArticleSet>')
 def materialize(self,p):
  pdf=fixtures.pdf();text='# Results\n\n'+('Important evidence. '*30)
  e.atomic(self.base/'pdf'/f'{p}.pdf',pdf);e.atomic(self.base/'markdown/raw'/f'{p}.md',text);e.atomic(self.base/'markdown'/f'{p}.md',text)
  e.write_json(self.base/'metadata/markdown'/f'{p}.json',{'pdfSha256':hashlib.sha256(pdf).hexdigest(),'rawSha256':hashlib.sha256(text.encode()).hexdigest(),'cleaningSignature':m.signature(m.config(e)),'rebuildEpoch':a.epoch(e,p)})
 def state(self,p='1'):return next(x for x in m.status(e)['items'] if x['pmid']==p)
 def test_touch_and_xml_reordering_keep_latest_but_pdf_content_change_invalidates(self):
  self.materialize('1');self.assertEqual(self.state()['markdownState'],'latest')
  path=self.base/'pdf/1.pdf';old=path.stat();os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns+10000000));self.xml(['2','1'])
  self.assertEqual(self.state()['markdownState'],'latest')
  body=path.read_bytes().replace(b'100',b'101');self.assertNotEqual(body,path.read_bytes());e.atomic(path,body);os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
  self.assertEqual(self.state()['markdownState'],'outdated');c.sync(e);d=next(d for d in c.documents(e) if d['pmid']=='1');self.assertEqual(d['sourceKind'],'pending_fulltext');self.assertEqual(d['chunks'],0)
 def test_cleaning_and_raw_edits_invalidate_markdown(self):
  self.materialize('1');self.assertEqual(self.state()['markdownState'],'latest')
  e.atomic(self.base/'markdown/raw/1.md','Edited raw. '*30);self.assertEqual(self.state()['markdownState'],'outdated')
  self.materialize('1');m.rpc(e,'settings.save',{'badrCleanup':False});self.assertEqual(self.state()['markdownState'],'latest')
 def test_markdown_edit_only_changes_vector_version(self):
  self.materialize('1');c.sync(e);before=c.documents(e)[0]['version']
  e.atomic(self.base/'markdown/1.md','Manually edited evidence. '*30);c.sync(e)
  self.assertEqual(self.state()['markdownState'],'latest');self.assertNotEqual(c.documents(e)[0]['version'],before)
 def test_removed_article_loses_all_derived_versions_but_keeps_pdf(self):
  self.materialize('1');c.sync(e);d=c.documents(e)[0];version=d['version'];generation=a.epoch(e,'1')
  with c.connect(e) as db:
   db.execute('INSERT INTO embeddings VALUES(?,?,?,?)',('model','hash',1,b'float'))
   db.execute('INSERT INTO embedding_owners VALUES(?,?,?)',('model','hash','1'))
   db.execute('INSERT INTO indexed VALUES(?,?,?,?)',('model','1',version,'input'))
  self.xml(['2']);f.reconcile(e)
  self.assertTrue((self.base/'pdf/redundant/1.pdf').exists())
  for name in ('markdown/1.md','markdown/raw/1.md','metadata/markdown/1.json','vectors/chunks/1.jsonl',f'vectors/sources/{version}.md'):self.assertFalse((self.base/name).exists(),name)
  with c.connect(e) as db:
   for table in ('documents','chunks','indexed','embedding_owners'):self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE pmid=?',('1',)).fetchone()[0],0)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0],0)
   self.assertTrue(db.execute('SELECT 1 FROM pending_vector_deletes WHERE version=?',(version,)).fetchone())
  self.xml(['1','2']);f.reconcile(e);self.assertTrue((self.base/'pdf/1.pdf').exists());self.assertFalse((self.base/'markdown/1.md').exists());self.assertGreater(a.epoch(e,'1'),generation)
  c.sync(e);d=c.documents(e)[0];self.assertEqual(d['state'],'blocked');self.assertFalse(d['indexed'])
 def test_removal_preserves_shared_cache_owned_by_remaining_article(self):
  c.sync(e)
  with c.connect(e) as db:
   db.execute('INSERT INTO embeddings VALUES(?,?,?,?)',('model','shared',1,b'float'))
   db.executemany('INSERT INTO embedding_owners VALUES(?,?,?)',[('model','shared','1'),('model','shared','2')])
  self.xml(['2']);f.reconcile(e)
  with c.connect(e) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0],1)
   self.assertEqual([r[0] for r in db.execute('SELECT pmid FROM embedding_owners')],['2'])
 def test_late_markdown_completion_after_remove_and_restore_is_discarded(self):
  import importlib.util,socket
  from unittest.mock import patch
  self.materialize('1');f.reconcile(e)
  spec=importlib.util.spec_from_file_location('marker_lifecycle_test',self.old[0]/'services/marker/worker.py');worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
  out=f.folder(e,'logs/markdown-race');job={'id':'race','state':'queued','mode':'clean','pmids':['1'],'config':m.config(e),'logPath':str(out),'completed':0,'skipped':0,'failed':0,'items':[]};e.write_json(m.job_path(e),job)
  clean=m.clean
  def during_conversion(text,cfg):
   result=clean(text,cfg);self.xml(['2']);f.reconcile(e);self.xml(['1','2']);f.reconcile(e);return result
  with patch.object(worker,'ROOT',e.ROOT),patch.object(m,'clean',side_effect=during_conversion),patch.object(socket.socket,'connect',socket.socket.connect),patch.dict(os.environ,{}):worker.run('test','race')
  self.assertEqual(m.read_job(e)['failed'],1);self.assertFalse((self.base/'markdown/1.md').exists());self.assertFalse((self.base/'markdown/raw/1.md').exists());self.assertTrue((self.base/'pdf/1.pdf').exists())

 def download_result(self,p,state,batch='b',created=1,attempt=True):
  e.execute('INSERT INTO batches(id,project,created,state,snapshot,config) VALUES(?,?,?,?,?,?)',(batch,e.PROJECT,created,'done','{}','{}'))
  e.execute('INSERT INTO items(batch,pmid,paper,state) VALUES(?,?,?,?)',(batch,p,'{}',state))
  if attempt:e.execute('INSERT INTO attempts(batch,pmid,stage,outcome,elapsed,detail) VALUES(?,?,?,?,?,?)',(batch,p,'pmc','failed',1,'{}'))
 def test_download_failure_settles_as_abstract_but_never_claims_pdf_exists(self):
  self.download_result('1','failed')
  state=self.state();self.assertTrue(state['abstractFallback']);self.assertTrue(state['sourceReady'])
  self.assertEqual(state['pdfState'],'missing');self.assertFalse(state['pdf'])
  self.assertFalse(self.state('2')['sourceReady']);c.sync(e)
  self.assertEqual(next(d for d in c.documents(e) if d['pmid']=='1')['sourceKind'],'pubmed_abstract')
 def test_failed_without_attempt_and_deleted_success_are_not_fallbacks(self):
  self.download_result('1','failed',attempt=False);self.assertFalse(self.state()['abstractFallback'])
  self.download_result('1','success',batch='new',created=2);self.assertFalse(self.state()['sourceReady'])
 def test_manual_pdf_refresh_registers_file_and_requires_fulltext_conversion(self):
  self.download_result('1','deferred');c.sync(e);before=c.documents(e)[0]['version'];self.assertTrue(self.state()['abstractFallback'])
  e.atomic(self.base/'pdf/1.pdf',fixtures.pdf());result=m.rpc(e,'reconcile',{})
  self.assertEqual(result['registered'],1);self.assertFalse(self.state()['abstractFallback']);self.assertEqual(self.state()['markdownState'],'missing')
  asset=json.loads(e.rows('SELECT data FROM assets WHERE pmid=?',('1',))[0]['data']);self.assertEqual(asset['source'],'用户提供的 PDF')
  doc=next(d for d in c.documents(e) if d['pmid']=='1');self.assertNotEqual(doc['version'],before);self.assertEqual(doc['sourceKind'],'pending_fulltext')
  self.assertEqual(m.rpc(e,'reconcile',{})['registered'],0)

 def test_malformed_manual_pdf_reports_invalid_without_breaking_refresh(self):
  e.atomic(self.base/'pdf/1.pdf',b'%PDF-1.4\nnot a document')
  result=m.rpc(e,'reconcile',{});self.assertEqual(len(result['invalid']),1)
  self.assertEqual(self.state()['pdfState'],'invalid');self.assertFalse(self.state()['sourceReady'])
