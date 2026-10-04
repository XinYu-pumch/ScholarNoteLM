import json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,storage,status_cache as cache,qa_service as qa,vector_chunks as chunks,vector_service as vectors

class StatusCacheTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory();e.ROOT,e.PROJECT=Path(self.tmp.name),'test'
  self.base=storage.project_dir(e.ROOT,e.PROJECT);self.xml=self.base/'pubmed/current.xml';self.publish()
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def publish(self,text='Evidence text. '*30,pmid='123'):
  e.atomic(self.xml,f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><ArticleTitle>Study</ArticleTitle><Abstract><AbstractText>{text}</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
 def inventory(self):return qa.rpc(e,'inventory',{})
 def test_unchanged_inventory_reuses_summary(self):
  first=self.inventory()
  with patch.object(qa,'corpus',side_effect=AssertionError('must reuse summary')):self.assertEqual(self.inventory(),first)
 def test_import_and_delete_invalidate_inventory(self):
  self.assertEqual(self.inventory()['papers'][0]['pmid'],'123');self.publish(pmid='456')
  self.assertEqual(self.inventory()['papers'][0]['pmid'],'456');e.atomic(self.xml,'<PubmedArticleSet/>')
  self.assertEqual(self.inventory()['coverage']['papers'],0)
 def test_every_material_dependency_invalidates(self):
  for relative in ['pdf/123.pdf','markdown/123.md','markdown/raw/123.md','markdown/assets/123/figure.png','metadata/markdown/123.json','metadata/conversion-settings.json','metadata/index-generation.json','metadata/index-cleared.json','metadata/pdf-cleared.json','metadata/corpus-membership.json']:
   with self.subTest(relative=relative):
    p=self.base/relative;before=cache.dependencies(e);e.atomic(p,'old');self.assertNotEqual(cache.dependencies(e),before)
    before=cache.dependencies(e);old=p.stat();p.write_text('new');os.utime(p,ns=(old.st_atime_ns,old.st_mtime_ns));self.assertNotEqual(cache.dependencies(e),before)
    before=cache.dependencies(e);p.unlink();self.assertNotEqual(cache.dependencies(e),before)
 def test_embedding_changes_and_index_clear_invalidate_actual_counts(self):
  chunks.sync(e);records=qa.corpus(e)[0];profile=vectors.profile(vectors.config(e))
  with chunks.connect(e) as c:
   for r in records:c.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?)',(profile,chunks.digest(r['text']),1,b'fake-vector'))
  self.assertGreater(self.inventory()['coverage']['searchableChunks'],0)
  e.write_json(e.ROOT/'config/embedding.json',{'baseUrl':'https://example.invalid/v1','model':'new-model'})
  self.assertEqual(self.inventory()['coverage']['searchableChunks'],0)
  (e.ROOT/'config/embedding.json').unlink();self.assertGreater(self.inventory()['coverage']['searchableChunks'],0)
  e.write_json(self.base/'metadata/index-cleared.json',{'cleared':True});self.assertEqual(self.inventory()['coverage']['searchableChunks'],0)
 def test_vector_write_in_wal_invalidates_without_checkpoint(self):
  chunks.sync(e)
  with chunks.connect(e) as c:
   c.execute('PRAGMA wal_autocheckpoint=0');before=cache.dependencies(e)
   c.execute('INSERT INTO embeddings VALUES(?,?,?,?)',('profile','hash',1,b'value'));c.commit()
   self.assertNotEqual(cache.dependencies(e),before)
 def test_empty_wal_and_unrelated_directory_churn_do_not_invalidate(self):
  self.base.joinpath('markdown').mkdir();self.base.joinpath('vectors').mkdir()
  before=cache.dependencies(e);(self.base/'vectors/chunks.sqlite3-wal').touch();(self.base/'markdown/redundant').mkdir()
  self.assertEqual(cache.dependencies(e),before)
 def test_inventory_does_not_read_vector_payload(self):
  chunks.sync(e);original=sqlite3.connect
  def connect(*args,**kwargs):
   c=original(*args,**kwargs)
   def authorize(action,table,column,*rest):
    if action==sqlite3.SQLITE_READ and table=='embeddings' and column=='vector':return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK
   c.set_authorizer(authorize);return c
  with patch.object(sqlite3,'connect',side_effect=connect):self.inventory()
 def test_change_during_compute_is_retried_not_published_as_current(self):
  calls=[]
  def compute():
   calls.append(1)
   if len(calls)==1:self.publish('Changed')
   return len(calls)
  self.assertEqual(cache.cached(e,'race',compute),2)
  self.assertEqual(cache.cached(e,'race',lambda:self.fail('should hit')),2)
 def test_continuously_changing_material_does_not_produce_current_summary(self):
  def compute():self.publish(os.urandom(5).hex());return 'old'
  with self.assertRaisesRegex(ValueError,'正在更新'):cache.cached(e,'racing',compute)
 def test_ui_racing_summary_is_marked_and_never_cached(self):
  calls=[]
  def compute(*_):calls.append(1);self.publish(os.urandom(5).hex());return [{'indexed':True}]
  with patch.object(chunks,'inspect_documents',side_effect=compute):
   first=cache.documents(e,'fixture');second=cache.documents(e,'fixture')
  self.assertTrue(first[0]['refreshing']);self.assertTrue(second[0]['refreshing']);self.assertEqual(len(calls),4)
 def test_progress_does_not_traverse_materials(self):
  e.write_json(vectors.job_path(e),{'id':'fixture','state':'done','completed':1,'items':[]})
  with patch.object(cache,'documents',side_effect=AssertionError('expensive path')):
   self.assertEqual(vectors.rpc(e,'progress',{})['job']['completed'],1)
 def test_cache_failure_and_corruption_are_recoverable(self):
  with patch.object(storage,'atomic',side_effect=OSError('read only')):self.assertEqual(cache.cached(e,'read-only',lambda:3),3)
  cache.cached(e,'corrupt',lambda:1)
  for p in (e.ROOT/'cache/status-snapshots').rglob('*.json'):p.write_text('{')
  self.assertEqual(cache.cached(e,'corrupt',lambda:2),2)
 def test_projects_are_isolated(self):
  self.inventory();e.PROJECT='other';other=storage.project_dir(e.ROOT,e.PROJECT)
  e.atomic(other/'pubmed/current.xml','<PubmedArticleSet/>');self.assertEqual(self.inventory()['coverage']['papers'],0)
  e.PROJECT='test';self.assertEqual(self.inventory()['coverage']['papers'],1)
 def test_start_bypasses_display_cache_and_rechecks_changed_material(self):
  self.inventory();self.publish('New authoritative source');expected=qa.current_signature(e)
  t=qa.rpc(e,'new',{});p={'model':'fixture','baseUrl':'http://localhost:1','apiKey':''}
  with patch.object(cache,'cached',side_effect=AssertionError('display cache must never authorize generation')),patch.object(qa,'models',return_value=(p,p)),patch.object(qa.subprocess,'Popen',return_value=Mock(pid=os.getpid())):
   result=qa.start(e,{'threadId':t['id'],'question':'Question','mode':'overview'})
  saved=qa.read(qa.runpath(e,result['id'])/'input.json');self.assertEqual(saved['sourceSignature'],expected)
 def test_removed_scope_is_rejected_before_start_even_after_cache_hit(self):
  self.inventory();t=qa.rpc(e,'new',{});self.publish(pmid='456');p={'model':'fixture'}
  with patch.object(qa,'models',return_value=(p,p)),patch.object(qa.subprocess,'Popen',side_effect=AssertionError('must not start')):
   with self.assertRaisesRegex(ValueError,'不在当前项目'):qa.start(e,{'threadId':t['id'],'question':'Question','pmids':['123'],'mode':'paper'})
 def test_thread_revision_detects_change_without_loading_answer(self):
  t=qa.rpc(e,'new',{});a=qa.rpc(e,'changes',{'threadId':t['id']})
  with patch.object(qa,'public_job',side_effect=AssertionError('no answer read')):self.assertEqual(qa.rpc(e,'changes',{'threadId':t['id']}),a)
  qa.rpc(e,'rename',{'threadId':t['id'],'name':'Renamed'});self.assertNotEqual(qa.rpc(e,'changes',{'threadId':t['id']})['revision'],a['revision'])

if __name__=='__main__':unittest.main()
