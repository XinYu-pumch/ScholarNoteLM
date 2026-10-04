"""PDF workflow freshness must not be confused with available/full-text evidence."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_artifact_state import ArtifactStateTests
import engine as e,artifact_state as a,markdown_service as m

class PdfFreshnessTests(unittest.TestCase):
 setUp=ArtifactStateTests.setUp
 tearDown=ArtifactStateTests.tearDown
 xml=ArtifactStateTests.xml
 materialize=ArtifactStateTests.materialize
 download_result=ArtifactStateTests.download_result
 def status(self):return m.status(e)['downloadStatus']
 def test_zotero_only_failure_is_not_a_full_download_attempt(self):
  self.download_result('1','failed');e.execute("UPDATE batches SET config=? WHERE id='b'",(json.dumps({'downloadMode':'zotero'}),))
  self.assertEqual(self.status()['pendingPmids'],['1','2']);self.assertNotIn('1',a.abstract_fallbacks(e))
  self.download_result('1','failed',batch='complete',created=2)
  self.download_result('1','failed',batch='local-later',created=3);e.execute("UPDATE batches SET config=? WHERE id='local-later'",(json.dumps({'downloadMode':'zotero'}),))
  self.assertEqual(self.status()['pendingPmids'],['2']);self.assertIn('1',a.abstract_fallbacks(e))
  self.materialize('2');self.assertTrue(self.status()['latest'])
 def test_complete_attempts_can_be_latest_with_missing_pdfs_and_no_abstract(self):
  self.xml(['1','2']);p=self.base/'pubmed/current.xml';p.write_text(p.read_text().replace('<Abstract>','<Ignored>').replace('</Abstract>','</Ignored>'))
  self.download_result('1','failed');self.download_result('2','deferred',batch='b2')
  s=self.status();self.assertTrue(s['latest']);self.assertEqual(s['missing'],2);self.assertEqual(s['attemptedMissing'],2)
  self.assertEqual(m.status(e)['sourceReadyCount'],0)
 def test_only_unattempted_added_paper_needs_download_and_removal_restores_latest(self):
  self.download_result('1','failed');self.download_result('2','deferred',batch='b2')
  self.assertTrue(self.status()['latest']);self.xml(['1','2','3'])
  self.assertEqual(self.status()['pendingPmids'],['3']);self.xml(['2','1']);self.assertTrue(self.status()['latest'])
 def test_cancelled_batch_does_not_settle_an_article_but_does_not_erase_prior_completion(self):
  self.download_result('1','failed');e.execute("UPDATE batches SET state='cancelled' WHERE id='b'")
  self.assertEqual(self.status()['pending'],2)
  self.download_result('1','failed',batch='complete',created=2)
  self.download_result('1','failed',batch='interrupted',created=3);e.execute("UPDATE batches SET state='paused' WHERE id='interrupted'")
  self.assertEqual(self.status()['pendingPmids'],['2'])
 def test_deleted_success_and_corrupt_pdf_need_download_again(self):
  self.download_result('1','failed');self.materialize('1');self.materialize('2');self.assertTrue(self.status()['latest'])
  self.download_result('1','success',batch='success',created=2);(self.base/'pdf/1.pdf').unlink();self.assertEqual(self.status()['pendingPmids'],['1'])
  (self.base/'pdf/2.pdf').write_bytes(b'broken');self.assertEqual(self.status()['pendingPmids'],['1','2'])
 def test_empty_project_and_failed_without_attempt_are_not_latest(self):
  self.download_result('1','failed',attempt=False);self.assertEqual(self.status()['pending'],2)
  self.xml([]);self.assertFalse(self.status()['latest'])
 def test_enabling_sources_invalidates_missing_only_but_tuning_throughput_does_not(self):
  self.download_result('1','deferred');self.materialize('2');self.assertTrue(self.status()['latest'])
  with patch.object(e,'config',return_value={**e.DEFAULTS,'enhanced':True}):self.assertEqual(self.status()['pendingPmids'],['1'])
  with patch.object(e,'config',return_value={**e.DEFAULTS,'mirrors':e.DEFAULTS['mirrors']+['https://new.example']}):self.assertFalse(self.status()['latest'])
  with patch.object(e,'config',return_value={**e.DEFAULTS,'pmcConcurrency':2,'s3ArticleTimeout':120}):self.assertTrue(self.status()['latest'])
 def test_new_pmcid_requires_another_attempt(self):
  self.download_result('1','failed');self.materialize('2')
  self.assertTrue(self.status()['latest']);p=self.base/'pubmed/current.xml';p.write_text(p.read_text().replace('</MedlineCitation>', '</MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData>',1))
  self.assertEqual(self.status()['pendingPmids'],['1'])
 def test_explicit_clear_does_not_reuse_failed_attempts_as_current(self):
  self.download_result('1','failed');self.download_result('2','deferred',batch='b2');self.assertTrue(self.status()['latest'])
  e.write_json(self.base/'metadata/pdf-cleared.json',{'time':1});self.assertEqual(self.status()['pending'],2)

if __name__=='__main__':unittest.main()
