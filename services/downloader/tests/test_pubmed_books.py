import sys,tempfile,unittest,xml.etree.ElementTree as ET,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,storage,corpus_files,vector_chunks,review_service,pubmed_xml,zotero_worker

class BookTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');self.old=e.ROOT,e.PROJECT;e.ROOT,e.PROJECT=Path(self.tmp.name),'booktest'
  self.base=storage.project_dir(e.ROOT,e.PROJECT);self.xml=Path(__file__).with_name('fixtures').joinpath('pubmed-book.xml').read_text()
  e.atomic(self.base/'pubmed/current.xml',self.xml)
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def test_membership_excludes_cited_pmid_and_preserves_book(self):
  self.assertEqual(corpus_files.current(e),{'123','456'})
  e.atomic(self.base/'pdf/456.pdf','fixture bytes')
  corpus_files.reconcile(e)
  self.assertTrue((self.base/'pdf/456.pdf').exists())
 def test_vector_metadata_and_chunks_include_book_without_reference_identifiers(self):
  articles,_=vector_chunks.xml_articles(e);self.assertEqual(set(articles),{'123','456'});a=articles['456']
  self.assertEqual(a['doi'],'10.1234/chapter');self.assertEqual(a['pmcid'],'');self.assertEqual(a['authors'],['Writer W'])
  self.assertEqual(a['title'],'Genetic conditions');self.assertEqual(a['journal'],'Reference book')
  self.assertEqual(a['year'],'2008');self.assertEqual(a['publicationTypes'],['Review']);self.assertEqual(a['bookAccession'],'NBK456')
  self.assertTrue(a['abstract'].startswith('BACKGROUND: Chapter abstract'))
  vector_chunks.sync(e);self.assertIn('456',{d['pmid'] for d in vector_chunks.documents(e)})
 def test_review_abstracts_and_zotero_identity(self):
  _,text,stats=review_service.abstracts(e);self.assertEqual(stats['total'],2);self.assertEqual(stats['abstractCount'],2)
  self.assertIn('PMID: 456',text);self.assertNotIn('PMID: 999',text)
  self.assertEqual(zotero_worker.current_doi('456'),'10.1234/chapter');self.assertIsNone(zotero_worker.current_doi('999'))
 def test_package_includes_book_material(self):
  e.atomic(self.base/'abstracts/456.md','Book abstract fixture')
  with patch.object(e,'idle_project'):result=e.package_current({'project':'booktest'})
  with zipfile.ZipFile(self.base/'packages/current-literature.zip') as z:self.assertIn('abstracts/456.md',z.namelist())

if __name__=='__main__':unittest.main()
