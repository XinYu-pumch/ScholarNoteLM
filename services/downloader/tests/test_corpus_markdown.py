import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e
import corpus_files as f
import markdown_service as m
import test_scihub_retry as fixtures

class CorpusMarkdownTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');self.old=(e.ROOT,e.PROJECT);e.ROOT,e.PROJECT=Path(self.tmp.name),'p';self.base=f.base(e)
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def xml(self,ids):e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID></MedlineCitation></PubmedArticle>' for p in ids)+'</PubmedArticleSet>')
 def put(self,name,content):e.atomic(self.base/name,content)
 def test_archive_restore_and_derived_files(self):
  self.xml(['1','2']);body=fixtures.pdf();self.put('pdf/1.pdf',body);self.put('pdf/2.pdf',body)
  for name in ['markdown/2.md','markdown/raw/2.md','abstracts/2.md']:self.put(name,'# Original\n\n'+('text '*30))
  self.put('markdown/assets/2/image.jpeg',b'picture')
  f.reconcile(e);self.xml(['1']);result=f.reconcile(e)
  self.assertEqual(result['archived'],1);self.assertFalse((self.base/'pdf/2.pdf').exists());self.assertEqual((self.base/'pdf/redundant/2.pdf').read_bytes(),body)
  self.assertFalse((self.base/'markdown/redundant/raw/2.md').exists());self.assertFalse((self.base/'markdown/redundant/assets/2/image.jpeg').exists());self.assertFalse((self.base/'markdown/raw/2.md').exists())
  self.xml(['1','2']);result=f.reconcile(e);self.assertEqual(result['restored'],1);self.assertEqual((self.base/'pdf/2.pdf').read_bytes(),body)
  self.assertFalse((self.base/'markdown/raw/2.md').exists());self.assertFalse((self.base/'markdown/assets/2/image.jpeg').exists())
  self.assertEqual(json.loads(e.one('SELECT data FROM assets WHERE pmid=?',('2',))['data'])['archived'],False)
 def test_empty_xml_archives_all_but_missing_or_invalid_does_not(self):
  self.put('pdf/1.pdf',fixtures.pdf());f.reconcile(e);self.assertTrue((self.base/'pdf/1.pdf').exists())
  self.put('pubmed/current.xml','<broken>')
  with self.assertRaises(Exception):f.reconcile(e)
  self.assertTrue((self.base/'pdf/1.pdf').exists());self.xml([]);f.reconcile(e);self.assertTrue((self.base/'pdf/redundant/1.pdf').exists())
 def test_no_abstract_retirement_preserves_materials(self):
  self.xml(['1','2']);self.put('pdf/2.pdf',fixtures.pdf())
  sources={'markdown/2.md':'edited text','markdown/raw/2.md':'original text','markdown/assets/2/image.png':b'image','markdown/history/2/previous.md':'previous text','metadata/markdown/2.json':'{}'}
  for name,content in sources.items():self.put(name,content)
  f.reconcile(e);self.xml(['1']);self.put('metadata/abstract-exclusions.json',json.dumps([{'pmid':'2','reason':'XML 无有效摘要'}]))
  f.reconcile(e)
  for name,content in sources.items():
   archived=self.base/'archive/without-abstract/2'/name
   self.assertEqual(archived.read_bytes(),content if isinstance(content,bytes) else content.encode())
   self.assertFalse((self.base/name).exists())
  self.assertTrue((self.base/'pdf/redundant/2.pdf').exists())
  self.assertEqual(json.loads((self.base/'archive/without-abstract/2/exclusion.json').read_text())['reason'],'XML 无有效摘要')
 def test_conflict_never_overwritten(self):
  self.xml([]);body=fixtures.pdf();self.put('pdf/1.pdf',body);self.put('pdf/redundant/1.pdf',b'user version')
  f.reconcile(e);self.assertEqual((self.base/'pdf/redundant/1.pdf').read_bytes(),b'user version');self.assertEqual(len(list((self.base/'pdf/redundant/conflicts').glob('1-*.pdf'))),1)
 def test_corrupt_redundant_not_reused(self):
  self.xml(['1']);self.put('pdf/redundant/1.pdf',b'not a PDF');result=f.reconcile(e)
  self.assertEqual(result['restored'],0);self.assertEqual(result['errors'][0]['pmid'],'1');self.assertFalse((self.base/'pdf/1.pdf').exists())
 def test_create_restores_before_download(self):
  self.xml(['1']);self.put('pdf/redundant/1.pdf',fixtures.pdf())
  with patch.object(e,'launch'):e.create({'project':'p','papers':[{'pmid':'1'}]})
  self.assertTrue((self.base/'pdf/1.pdf').exists());self.assertFalse((self.base/'pdf/redundant/1.pdf').exists())
 def test_cleanup_off_retains_short_and_lists(self):
  text='# Title\n\nshort\n\n- bullet\n';output,removed=m.clean(text,{'badrCleanup':False,'removeLines':[]});self.assertEqual(output,text);self.assertEqual(removed,[])
 def test_idle_reconcile_writes_nothing(self):
  # Status polling reconciles repeatedly; an unchanged project must not create, delete or log anything.
  self.xml(['1']);self.put('pdf/1.pdf',fixtures.pdf());logs=lambda:sorted((self.base/'logs').glob('corpus-files-*.json'))
  for _ in range(3):self.assertEqual(f.reconcile(e)['deletedDerived'],0)
  self.assertEqual(logs(),[]);self.assertFalse((self.base/'markdown/redundant').exists());self.assertFalse((self.base/'abstracts/redundant').exists())
 def test_symlink_refused(self):
  self.xml(['1']);outside=e.ROOT/'outside';outside.mkdir();(self.base/'pdf').symlink_to(outside)
  with self.assertRaises(ValueError):f.reconcile(e)
 def test_bad_first_pdf_does_not_abort_following_articles(self):
  import importlib.util
  source=self.old[0]/'services/marker/worker.py';spec=importlib.util.spec_from_file_location('marker_worker_test',source);worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
  self.xml(['1','2']);self.put('pdf/1.pdf',b'corrupt');body=fixtures.pdf();self.put('pdf/2.pdf',body)
  cfg=dict(m.DEFAULTS);self.put('markdown/raw/2.md','# Heading\n\n'+'text '*30);self.put('markdown/2.md','existing')
  self.put('metadata/markdown/2.json',json.dumps({'pdfSha256':hashlib.sha256(body).hexdigest(),'cleaningSignature':m.signature(cfg)}))
  report=self.base/'logs/markdown-test';report.mkdir(parents=True)
  job={'id':'test','state':'queued','mode':'convert','pmids':['1','2'],'config':cfg,'logPath':str(report),'completed':0,'skipped':0,'failed':0,'items':[]}
  e.write_json(m.job_path(e),job)
  import socket,os
  with patch.object(worker,'ROOT',e.ROOT),patch.object(socket.socket,'connect',socket.socket.connect),patch.dict(os.environ,{}):worker.run('p','test')
  result=m.read_job(e);self.assertEqual(result['state'],'done');self.assertEqual(result['failed'],1);self.assertEqual(result['skipped'],1)
 def test_worker_selection_and_versioned_signatures(self):
  for pages,requested,effective in [(3,1,1),(39,1,1),(40,4,4),(137,4,4)]:self.assertEqual(m.text_workers('auto',pages),(requested,effective))
  self.assertEqual(m.text_workers(8,26),(8,2));self.assertEqual(m.text_workers(16,3),(16,1))
  old={'device':'auto','badrCleanup':True,'removeLines':[]}
  legacy=hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()
  for workers in ('auto',1,2,4,8,16):
   self.assertNotEqual(m.signature({**old,'pdftextWorkers':workers}),legacy)
   self.assertEqual(m.signature({**old,'pdftextWorkers':workers}),m.signature(old))
  for bad in (0,-1,3,True,4.0,'4',None,{}):
   with self.assertRaises(ValueError):m.rpc(e,'settings.save',{'pdftextWorkers':bad})
  self.assertFalse((e.ROOT/'config/markdown.json').exists())
  self.assertEqual(m.rpc(e,'settings.save',{'pdftextWorkers':4})['config']['pdftextWorkers'],4)
 def test_handoff_only_done_and_once(self):
  self.xml(['1']);self.put('pdf/1.pdf',fixtures.pdf())
  with patch.object(e,'launch'),patch.object(m,'readiness',return_value={'ready':True}):
   created=e.create({'project':'p','papers':[{'pmid':'1'}],'convertAfter':True})
  bid=created['id']
  def batch():return e.one('SELECT * FROM batches WHERE id=?',(bid,))
  with patch.object(m,'rpc',return_value={'id':'md','count':1}) as start:
   for state in ('queued','running','paused','cancelled'):
    e.execute('UPDATE batches SET state=? WHERE id=?',(state,bid));e.finish_markdown(batch());start.assert_not_called()
   e.execute("UPDATE batches SET state='done' WHERE id=?",(bid,))
   self.assertEqual(e.finish_markdown(batch())['state'],'started')
   self.assertEqual(e.finish_markdown(batch())['id'],'md');self.assertEqual(start.call_count,1)
 def test_handoff_lock_contention_is_not_failure(self):
  import storage
  self.xml(['1']);self.put('pdf/1.pdf',fixtures.pdf())
  with patch.object(e,'launch'),patch.object(m,'readiness',return_value={'ready':True}):created=e.create({'project':'p','papers':[{'pmid':'1'}],'convertAfter':True})
  e.execute("UPDATE batches SET state='done' WHERE id=?",(created['id'],));b=e.one('SELECT * FROM batches WHERE id=?',(created['id'],))
  with storage.file_lock(e.batch_dir(b)/'markdown-followup.lock'):
   self.assertEqual(e.finish_markdown(b)['state'],'waiting')
  self.assertFalse(list(e.batch_dir(b).glob('markdown-followup-*.json')))
 def test_handoff_no_pdf_and_dead_owner(self):
  self.xml(['1'])
  with patch.object(e,'launch'),patch.object(m,'readiness',return_value={'ready':True}):created=e.create({'project':'p','papers':[{'pmid':'1'}],'convertAfter':True})
  e.execute("UPDATE batches SET state='done' WHERE id=?",(created['id'],));b=e.one('SELECT * FROM batches WHERE id=?',(created['id'],))
  with patch.object(m,'rpc') as start:
   self.assertEqual(e.finish_markdown(b)['state'],'empty');start.assert_not_called()
  for path in e.batch_dir(b).glob('markdown-followup-*.json'):path.unlink()
  b['owner']=123
  with patch.object(e,'process_alive',return_value=False),patch.object(m,'rpc') as start:
   self.assertEqual(e.finish_markdown(b)['state'],'stopped');start.assert_not_called()
 def test_handoff_receipt_recovers_without_duplicate_job(self):
  self.xml(['1']);self.put('pdf/1.pdf',fixtures.pdf())
  e.write_json(m.job_path(e),{'id':'existing','state':'done','requestId':'request','pmids':['1']})
  with patch.object(m.subprocess,'Popen') as spawn:
   result=m.rpc(e,'start',{'requestId':'request'})
   self.assertEqual(result['id'],'existing');spawn.assert_not_called()
   self.assertEqual(m.rpc(e,'start',{'requestId':'request'}),result)
 def test_retry_creates_a_fresh_automatic_conversion_cycle(self):
  self.xml(['1']);self.put('pdf/1.pdf',fixtures.pdf())
  with patch.object(e,'launch'),patch.object(m,'readiness',return_value={'ready':True}):created=e.create({'project':'p','papers':[{'pmid':'1'}],'convertAfter':True})
  bid=created['id'];e.execute("UPDATE batches SET state='done' WHERE id=?",(bid,));e.execute("UPDATE items SET state='failed' WHERE batch=?",(bid,))
  def batch():return e.one('SELECT * FROM batches WHERE id=?',(bid,))
  with patch.object(m,'rpc',return_value={'id':'md','count':1}) as start,patch.object(e,'launch'):
   e.finish_markdown(batch());first=start.call_args.args[2]['requestId']
   e.control({'project':'p','id':bid,'command':'retry'})
   self.assertTrue(json.loads(batch()['config'])['convertAfter'])
   e.execute("UPDATE batches SET state='done' WHERE id=?",(bid,));e.finish_markdown(batch())
   self.assertNotEqual(start.call_args.args[2]['requestId'],first);self.assertEqual(start.call_count,2)
 def test_manual_conversion_cannot_overtake_automatic_download(self):
  self.xml(['1']);self.put('pdf/1.pdf',fixtures.pdf())
  with patch.object(e,'launch'),patch.object(m,'readiness',return_value={'ready':True}):e.create({'project':'p','papers':[{'pmid':'1'}],'convertAfter':True})
  with self.assertRaisesRegex(ValueError,'下载并转换任务尚未结束'):m.rpc(e,'start',{})
 def test_automatic_download_requires_ready_models(self):
  self.xml(['1'])
  with patch.object(m,'readiness',return_value={'ready':False}),patch.object(e,'launch') as launch:
   with self.assertRaisesRegex(ValueError,'本地 Markdown 模型'):e.create({'project':'p','papers':[{'pmid':'1'}],'convertAfter':True})
   launch.assert_not_called();self.assertFalse(e.rows('SELECT * FROM batches'))
