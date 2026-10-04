"""Project-wide missing-PDF snapshot and its two explicit refresh triggers."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,corpus_files as files,markdown_service as markdown
from test_downloads import pdf

class MissingPdfReportTests(unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test'
  # Exercise project-ID -> folder mapping, not a hard-coded workspace path.
  e.write_json(e.ROOT/'config/storage.json',{'workspace':str(e.ROOT/'workspace'),'projects':{'test':'Reports'}})
  self.base=files.base(e);self.output=self.base/'literature_without_pdf.txt';self.sources=self.base/'literature_pdf_sources.txt';self.xml(['10','1','2'])
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def xml(self,ids):
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>Study {p}</ArticleTitle></Article></MedlineCitation></PubmedArticle>' for p in ids)+'</PubmedArticleSet>')
 async def test_completed_subset_download_refreshes_whole_corpus_and_keeps_batch_report(self):
  with patch.object(e,'launch'):created=e.create({'project':'test','papers':[{'pmid':'1','pmcid':'PMC1','title':'Study 1'}]})
  batch=e.one('SELECT * FROM batches WHERE id=?',(created['id'],))
  async def source(client,paper,path,b,cfg):path.write_bytes(pdf());return {'source':'PMC S3'},''
  with patch.object(e,'source_s3',source):await e.run_batch(batch)
  self.assertEqual(e.one('SELECT state FROM batches WHERE id=?',(batch['id'],))['state'],'done')
  self.assertEqual(self.output.read_text(),'2\n10\n')
  self.assertIn('1\tpdf/1.pdf\tPMC S3',self.sources.read_text())
  historical=e.batch_dir(batch)/'literature_without_pdf.txt';self.assertEqual(historical.read_text(),'')
  e.atomic(self.base/'pdf/2.pdf',pdf());markdown.rpc(e,'reconcile',{})
  self.assertEqual(self.output.read_text(),'10\n');self.assertEqual(historical.read_text(),'')
  self.assertIn('2\tpdf/2.pdf\t用户提供的 PDF',self.sources.read_text())
 def test_local_check_tracks_added_deleted_invalid_pdfs_and_current_membership(self):
  e.atomic(self.base/'pdf/1.pdf',pdf());e.atomic(self.base/'pdf/2.pdf',b'not a PDF')
  result=markdown.rpc(e,'reconcile',{});self.assertEqual(result['missingPdfCount'],2);self.assertEqual(self.output.read_text(),'2\n10\n')
  e.atomic(self.base/'pdf/2.pdf',pdf());(self.base/'pdf/1.pdf').unlink();self.xml(['1','2'])
  markdown.rpc(e,'reconcile',{});self.assertEqual(self.output.read_text(),'1\n')
 def test_complete_or_empty_corpus_produces_empty_file(self):
  for p in ['1','2','10']:e.atomic(self.base/f'pdf/{p}.pdf',pdf())
  files.update_missing_pdf_report(e);self.assertEqual(self.output.read_bytes(),b'')
  self.xml([]);files.update_missing_pdf_report(e);self.assertEqual(self.output.read_bytes(),b'')
 def test_invalid_or_absent_xml_does_not_erase_previous_report(self):
  files.update_missing_pdf_report(e);previous=self.output.read_bytes();previous_sources=self.sources.read_bytes()
  e.atomic(self.base/'pubmed/current.xml','<broken>')
  with self.assertRaises(Exception):files.update_missing_pdf_report(e)
  self.assertEqual(self.output.read_bytes(),previous)
  self.assertEqual(self.sources.read_bytes(),previous_sources)
  (self.base/'pubmed/current.xml').unlink();files.update_missing_pdf_report(e);self.assertEqual(self.output.read_bytes(),previous)
  self.assertEqual(self.sources.read_bytes(),previous_sources)
 def test_check_restores_redundant_pdf_before_writing_report(self):
  e.atomic(self.base/'pdf/redundant/2.pdf',pdf());markdown.rpc(e,'reconcile',{})
  self.assertTrue((self.base/'pdf/2.pdf').exists());self.assertEqual(self.output.read_text(),'1\n10\n')
 def asset(self,p,source):
  path=self.base/f'pdf/{p}.pdf';e.atomic(path,pdf())
  info={**e.validate_pdf(path),'source':source,'pmid':p,'path':f'pdf/{p}.pdf'}
  e.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',(e.PROJECT,p,json.dumps(info)))
 def source_rows(self):
  text=self.sources.read_text();return text.split('PMID\tPDF 文件\t来源\n',1)[1].splitlines()
 def test_sources_include_all_current_pdfs_counts_and_numeric_order(self):
  self.asset('1','Sci-Hub');self.asset('2','Zotero');self.asset('10','Sci-Hub')
  e.atomic(self.base/'pdf/redundant/99.pdf',pdf())
  result=files.update_missing_pdf_report(e)
  self.assertEqual(result['pdfSourcesReport'],str(self.sources));self.assertEqual(result['pdfSourcesCount'],3)
  self.assertEqual(self.source_rows(),['1\tpdf/1.pdf\tSci-Hub','2\tpdf/2.pdf\tZotero','10\tpdf/10.pdf\tSci-Hub'])
  self.assertIn('Sci-Hub\t2\n',self.sources.read_text());self.assertIn('Zotero\t1\n',self.sources.read_text())
  self.assertNotIn('99.pdf',self.sources.read_text())
 def test_check_tracks_manual_replacement_addition_removal_and_empty_corpus(self):
  self.asset('1','Sci-Hub');self.asset('2','Zotero')
  markdown.rpc(e,'reconcile',{});self.assertIn('2\tpdf/2.pdf\tZotero',self.source_rows())
  e.atomic(self.base/'pdf/2.pdf',pdf()+b'\n%external replacement')
  e.atomic(self.base/'pdf/10.pdf',pdf());(self.base/'pdf/1.pdf').unlink()
  markdown.rpc(e,'reconcile',{})
  self.assertEqual(self.source_rows(),['2\tpdf/2.pdf\t用户提供的 PDF','10\tpdf/10.pdf\t用户提供的 PDF'])
  self.xml([]);markdown.rpc(e,'reconcile',{})
  self.assertEqual(self.source_rows(),[]);self.assertIn('有效 PDF 总数：0',self.sources.read_text())
 def test_unknown_or_stale_origin_is_not_guessed_and_invalid_pdfs_excluded(self):
  self.asset('1','Sci-Hub');e.atomic(self.base/'pdf/1.pdf',pdf()+b'\n%changed')
  e.atomic(self.base/'pdf/2.pdf',pdf());e.atomic(self.base/'pdf/10.pdf',b'invalid PDF')
  files.update_missing_pdf_report(e)
  self.assertEqual(self.source_rows(),['1\tpdf/1.pdf\t未知（无匹配的来源记录）','2\tpdf/2.pdf\t未知（无匹配的来源记录）'])
  self.assertEqual(self.output.read_text(),'10\n')
 async def test_subset_download_report_also_includes_previously_downloaded_pdfs(self):
  self.asset('2','Zotero');self.asset('10','Unpaywall')
  with patch.object(e,'launch'):created=e.create({'project':'test','papers':[{'pmid':'1','pmcid':'PMC1','title':'Study 1'}]})
  batch=e.one('SELECT * FROM batches WHERE id=?',(created['id'],))
  async def source(client,paper,path,b,cfg):path.write_bytes(pdf());return {'source':'Sci-Net'},''
  with patch.object(e,'source_s3',source):await e.run_batch(batch)
  self.assertEqual(self.source_rows(),['1\tpdf/1.pdf\tSci-Net','2\tpdf/2.pdf\tZotero','10\tpdf/10.pdf\tUnpaywall'])
 async def test_download_reuse_does_not_assign_old_origin_to_replaced_file(self):
  self.asset('1','Zotero');e.atomic(self.base/'pdf/1.pdf',pdf()+b'\n%manual replacement')
  with patch.object(e,'launch'):created=e.create({'project':'test','papers':[{'pmid':'1','pmcid':'PMC1','title':'Study 1'}]})
  await e.run_batch(e.one('SELECT * FROM batches WHERE id=?',(created['id'],)))
  self.assertEqual(self.source_rows(),['1\tpdf/1.pdf\t已有本地 PDF（原始来源未知）'])
 def test_restore_keeps_verified_source_but_not_replaced_backup_origin(self):
  self.asset('2','Zotero');self.xml(['1']);markdown.rpc(e,'reconcile',{})
  self.xml(['1','2']);markdown.rpc(e,'reconcile',{})
  self.assertEqual(self.source_rows(),['2\tpdf/2.pdf\tZotero'])
  self.xml(['1']);markdown.rpc(e,'reconcile',{})
  e.atomic(self.base/'pdf/redundant/2.pdf',pdf()+b'\n%backup replaced')
  self.xml(['1','2']);markdown.rpc(e,'reconcile',{})
  self.assertEqual(self.source_rows(),['2\tpdf/2.pdf\t冗余目录恢复（原始来源未知）'])
