import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,corpus_files as f,library_service as l,vector_chunks as c,vector_service as v,review_service as r,review_writing as w,markdown_service as m
from test_scihub_retry import pdf

class LibraryTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test';self.base=f.base(e)
  self.xml();e.atomic(self.base/'pdf/1.pdf',pdf());e.atomic(self.base/'pdf/redundant/2.pdf',pdf());f.reconcile(e)
  text='Full source evidence. '*30
  e.atomic(self.base/'markdown/raw/1.md',text);e.atomic(self.base/'markdown/1.md',text)
  e.write_json(self.base/'metadata/markdown/1.json',{'pdfSha256':e.validate_pdf(self.base/'pdf/1.pdf')['sha256'],'rawSha256':hashlib.sha256(text.encode()).hexdigest(),'cleaningSignature':m.signature(m.config(e))})
  c.sync(e);r.rpc(e,'create',{'name':'Review1','topic':'Topic'})
  e.atomic(self.base/'review/Review1/review_parts/section_1.json','existing review');e.atomic(self.base/'notes/note.md','user note')
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def xml(self,title='Full <i>nested</i> title'):
  e.atomic(self.base/'pubmed/current.xml',f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>{title}</ArticleTitle><Journal><Title>Complete journal name</Title><JournalIssue><PubDate><Year>2026</Year><Month>Sep</Month></PubDate></JournalIssue></Journal><Abstract><AbstractText>'+('Abstract evidence. '*25)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
 def clear(self,scope='index',redundant=False):
  with patch.object(l,'running',return_value=[]):return l.clear_idle(e,{'scope':scope,'includeRedundant':redundant})
 def test_clear_index_preserves_sources_and_invalidates_review_without_resurrection(self):
  before=w.source_signature(e);self.clear()
  self.assertNotEqual(before,w.source_signature(e));self.assertTrue((self.base/'pdf/1.pdf').is_file());self.assertTrue((self.base/'markdown/1.md').is_file())
  c.sync(e);status=v.rpc(e,'status',{});self.assertEqual(status['readyDocuments'],0);self.assertTrue(status['cleared']);self.assertFalse((self.base/'vectors').exists())
  self.assertEqual((self.base/'review/Review1/review_parts/section_1.json').read_text(),'existing review')
 def test_clear_markdown_cascades_but_keeps_pdfs(self):
  self.clear('markdown');self.assertFalse((self.base/'markdown').exists());self.assertFalse((self.base/'vectors').exists());self.assertTrue((self.base/'pdf/1.pdf').exists());self.assertTrue((self.base/'pdf/redundant/2.pdf').exists())
 def test_clear_pdf_keeps_redundant_by_default_and_does_not_restore(self):
  e.atomic(self.base/'pdf/redundant/1.pdf',pdf());self.clear('pdf');m.status(e)
  self.assertFalse((self.base/'pdf/1.pdf').exists());self.assertTrue((self.base/'pdf/redundant/1.pdf').exists());self.assertTrue((self.base/'pubmed/current.xml').exists());self.assertEqual((self.base/'notes/note.md').read_text(),'user note')
  m.rpc(e,'reconcile',{});self.assertTrue((self.base/'pdf/1.pdf').exists())
 def test_clear_pdf_explicitly_includes_redundant(self):
  self.clear('pdf',True);self.assertFalse((self.base/'pdf').exists())
 def test_clear_refuses_active_worker_before_removal(self):
  with patch.object(l,'running',return_value=[('vector',{})]),self.assertRaises(ValueError):l.clear_idle(e,{'scope':'pdf','includeRedundant':True})
  self.assertTrue((self.base/'pdf/1.pdf').exists());self.assertTrue((self.base/'vectors/chunks.sqlite3').exists())
 def test_clear_preflights_symlinks_before_deleting_anything(self):
  outside=e.ROOT/'outside';outside.write_text('safe');(self.base/'markdown/link').symlink_to(outside)
  with self.assertRaises(ValueError):self.clear('markdown')
  self.assertTrue((self.base/'vectors/chunks.sqlite3').exists());self.assertEqual(outside.read_text(),'safe')
 def test_long_metadata_full_unicode_and_date_precision(self):
  title='非常长的完整篇名'*400;self.xml(title);c.sync(e);d=c.documents(e)[0]
  self.assertEqual(d['metadata']['title'],title);self.assertEqual(d['metadata']['publicationDate'],'2026 Sep');self.assertEqual(d['metadata']['publicationDates']['journal']['precision'],'month')
  with c.connect(e) as db:record=c.records_for(db,d['version'],d['metadata'])[0]
  self.assertEqual(c.chroma_metadata(record,d['version'],'hash')['title'],title)
 def test_csv_creation_is_validated_before_directory_and_preserves_source(self):
  with self.assertRaises(ValueError):r.rpc(e,'create',{'name':'Bad','outlineSource':'file','csv':'1.1,Missing parent','fileName':'bad.csv'})
  self.assertFalse((self.base/'review/Bad').exists())
  csv='\ufeffSerial,Title\r\n1,"Introduction, scope"\r\n1.1,Background\r\n'
  d=r.rpc(e,'create',{'name':'Imported','outlineSource':'file','csv':csv,'fileName':'中文框架.csv'})
  root=self.base/'review/Imported';self.assertEqual((root/'imported.csv').read_bytes(),csv.encode());self.assertEqual(d['rows'][0]['title'],'Introduction, scope');self.assertTrue(d['hasOriginal'])
  d=r.rpc(e,'save',{'name':'Imported','revision':d['version']['revision'],'rows':[{'serial':'1','title':'Changed'}]})
  d=r.rpc(e,'restore',{'name':'Imported','revision':d['version']['revision']});self.assertEqual(len(d['rows']),2)
 def test_workflow_blocks_manual_starts_and_accepts_its_own_stage(self):
  e.write_json(l.path(e),{'id':'testflow','state':'running','mode':'update','pid':0})
  with self.assertRaises(ValueError):l.check_owner(e,{})
  l.check_owner(e,{'workflowId':'testflow'})
 def test_single_conversion_does_not_request_index_handoff(self):
  with patch.object(m,'readiness',return_value={'ready':True}),patch.object(m.subprocess,'Popen') as spawn:
   spawn.return_value.pid=0;m.rpc(e,'start',{})
  self.assertFalse(m.read_job(e)['indexAfter'])
 def test_resume_owned_download_can_continue_during_pipeline(self):
  e.write_json(l.path(e),{'id':'flow','downloadId':'batch1','state':'running','mode':'update','pid':0})
  with patch.object(e,'dispatch_rpc',return_value={'ok':True}) as dispatch:
   e.rpc('control',{'project':e.PROJECT,'id':'batch1','command':'resume'})
   self.assertEqual(dispatch.call_args.args[1]['workflowId'],'flow')
   with self.assertRaises(ValueError):e.rpc('control',{'project':e.PROJECT,'id':'unrelated','command':'resume'})
 def test_coordinator_cancel_before_work_leaves_sources_intact(self):
  e.write_json(l.path(e),{'id':'flow','mode':'update','state':'queued','stage':'waiting','pid':0,'created':0,'stages':[],'xmlHash':l.xml_hash(e)})
  e.atomic(self.base/'metadata/library-stop-flow','stop')
  with patch.object(l,'running',return_value=[]),patch.object(e,'rpc',side_effect=AssertionError('No stage should start')):l.run(e,'flow')
  self.assertEqual(l.job(e)['state'],'stopped');self.assertTrue((self.base/'pdf/1.pdf').exists())
