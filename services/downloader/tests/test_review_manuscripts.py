import json,os,shutil,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,review_service as r,review_writing as w,review_manuscripts as m,storage
from test_review_writing import PROFILE

A='1,Original\n1.1,Leaf\n2,Conclusion\n'
B='1,New first heading\n2,Original\n2.1,Leaf\n3,Conclusion\n'
class ManuscriptTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory();e.ROOT,e.PROJECT=Path(self.tmp.name),'test'
  self.base=storage.project_dir(e.ROOT,e.PROJECT);e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet/>')
  self.detail=r.rpc(e,'create',{'name':'Test','outlineSource':'file','fileName':'A.csv','csv':A,'topic':'Topic A','requirements':'Keep evidence'})
  self.path=r.work(e,'Test');self.profile=patch.object(r,'profile',return_value=PROFILE);self.profile.start()
 def tearDown(self):self.profile.stop();e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def call(self,op,**a):return r.rpc(e,op,{'name':'Test',**a})
 def seed(self,tag='A'):
  rows=w.rows_at(e,self.path);cfg=w.config(self.path);m.new_round(e,'Test',rows,'Topic '+tag,cfg)
  for u in w.tree_units(rows):
   sections=[{'node_id':n['id'],'markdown':'Body '+tag+' '+n['serial']} for n in u['nodes']]
   saved={'created':1,'sections':sections,'evidence':{},'signature':w.unit_signature(u,cfg,'Topic A',w.source_signature(e),w.profile_signature(PROFILE),w.retrieval.signature(e.ROOT))}
   e.write_json(self.path/'sections'/f'{u["id"]}.json',saved);e.write_json(self.path/'review_parts'/f'section_{u["serial"]}.json',w.review_format.public_part(u,sections,{}))
 def change(self,csv):
  d=self.call('get');return self.call('import',revision=d['version']['revision'],csv=csv)
 def test_whole_outline_expiry_restore_and_no_implicit_body_switch(self):
  self.seed();self.assertEqual(self.call('writing.status')['latest'],2)
  self.change(B);state=self.call('writing.status');self.assertTrue(state['outlineChanged']);self.assertEqual(state['latest'],0)
  self.assertEqual(state['rows'][0]['title'],'Original');self.assertIn('Body A',self.call('writing.preview')['markdown'])
  d=self.call('get');self.call('restore',revision=d['version']['revision']);self.assertFalse(self.call('writing.status')['outlineChanged']);self.assertEqual(self.call('writing.status')['latest'],2)
  self.change(B);self.call('writing.reset',confirm=True);self.seed('B');self.assertFalse(self.call('writing.status')['outlineChanged'])
  d=self.call('get');self.call('restore',revision=d['version']['revision']);self.assertTrue(self.call('writing.status')['outlineChanged'])
  self.assertIn('Body B',self.call('writing.preview')['markdown']);self.assertNotIn('Body A',self.call('writing.preview')['markdown'])
  self.change(B);self.assertFalse(self.call('writing.status')['outlineChanged'])
 def test_copy_workspace_is_independent_and_original_can_be_restored(self):
  self.seed();copy=r.rpc(e,'create',{'name':'Copy','outlineSource':'workspace','sourceWorkspace':'Test'})
  self.assertEqual(copy['version']['topic'],'Topic A');self.assertEqual(copy['version']['requirements'],'Keep evidence')
  self.assertEqual(copy['workspace']['outlineSource']['workspace'],'Test');self.assertTrue(copy['hasOriginal'])
  self.assertNotEqual(copy['rows'][0]['id'],self.detail['rows'][0]['id']);self.assertFalse((r.work(e,'Copy')/'sections').exists())
  self.change(B);self.assertEqual(r.rpc(e,'get',{'name':'Copy'})['rows'][0]['title'],'Original')
  r.rpc(e,'save',{'name':'Copy','revision':0,'topic':'Topic A','rows':[{'serial':'1','title':'Edited'}]})
  self.assertEqual(r.rpc(e,'restore',{'name':'Copy','revision':1})['rows'][0]['title'],'Original')
  with self.assertRaises(ValueError):r.rpc(e,'create',{'name':'Bad','outlineSource':'workspace','sourceWorkspace':'../elsewhere'})
 def test_reset_preserves_exports_and_standalone_manuscript(self):
  self.seed();first=w.export(e,'Test','html');old=Path(first['path']).read_bytes()
  e.atomic(self.path/'retrieval/temp.json','{}');e.atomic(self.path/'logs/temp/file.log','log');e.atomic(self.path/'prompts/temp.json','{}')
  with self.assertRaisesRegex(ValueError,'确认'):self.call('writing.reset')
  state=self.call('writing.reset',confirm=True);self.assertFalse(state['hasContent']);self.assertEqual(state['prepared'],0)
  self.assertEqual(Path(first['path']).read_bytes(),old);self.assertTrue((self.path/'outline.csv').exists())
  for d in m.RESET_DIRS:self.assertFalse((self.path/d).exists())
  items=self.call('writing.manuscripts');self.assertEqual(len(items),1);self.assertFalse(items[0]['partial'])
  e.atomic(self.path/'outline.csv','1,Changed independently\n');(self.base/'pubmed/current.xml').unlink()
  with patch.object(w,'source_signature',side_effect=AssertionError('Historical export must be offline')),patch.object(r,'profile',side_effect=AssertionError('No model needed')):
   for fmt in ('md','html','docx'):
    exported=self.call('writing.manuscript.export',id=items[0]['id'],format=fmt);self.assertTrue(Path(exported['path']).is_file())
   preview=self.call('writing.manuscript',id=items[0]['id']);self.assertIn('Body A',json.dumps(preview));self.assertNotIn('Changed independently',json.dumps(preview))
 def test_archive_failure_does_not_clear_or_modify_outline(self):
  self.seed();body=(self.path/'sections'/next((self.path/'sections').iterdir()).name).read_bytes()
  with patch.object(m,'save',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):self.call('writing.reset',confirm=True)
   with self.assertRaises(OSError):self.change(B)
  self.assertEqual((self.path/'outline.csv').read_text(),r.to_csv(r.parse_csv(A)))
  self.assertIn(body,[f.read_bytes() for f in (self.path/'sections').glob('*.json')])
 def test_saved_copy_dedup_integrity_and_export_names(self):
  self.seed();one=m.save(e,'Test');two=m.save(e,'Test');self.assertEqual(one['id'],two['id']);self.assertEqual(len(m.listing(e,'Test')),1)
  a=w.export(e,'Test','md');b=w.export(e,'Test','md');self.assertNotEqual(a['path'],b['path']);self.assertNotEqual(Path(a['path']).name,Path(b['path']).name)
  document=self.path/'manuscripts'/one['id']/'document.json';bad=json.loads(document.read_text());bad['topic']='Tampered';e.write_json(document,bad)
  with self.assertRaisesRegex(ValueError,'校验'):self.call('writing.reset',confirm=True)
  self.assertTrue((self.path/'sections').exists())
 def test_new_prepare_resets_but_resume_preserves_current_artifacts(self):
  self.seed();runtime=e.ROOT/'runtime';runtime.touch()
  with patch.object(w,'runtime',return_value=runtime),patch.object(w.retrieval,'ready',return_value=True),patch.object(w.subprocess,'Popen') as process:
   process.return_value.pid=os.getpid()
   with self.assertRaisesRegex(ValueError,'确认'):self.call('writing.prepare')
   self.assertTrue((self.path/'sections').exists())
   self.call('writing.prepare',confirm=True);self.assertFalse((self.path/'sections').exists());self.assertEqual(len(m.listing(e,'Test')),1)
   j=r.read(self.path/'writing-job.json');j.update(state='cancelled');e.write_json(self.path/'writing-job.json',j)
   e.atomic(self.path/'retrieval/keep.json','{}');round_id=m.context(e,'Test')['id']
   self.call('writing.prepare.resume');self.assertEqual(m.context(e,'Test')['id'],round_id);self.assertTrue((self.path/'retrieval/keep.json').exists())
   j=r.read(self.path/'writing-job.json');j.update(state='failed');e.write_json(self.path/'writing-job.json',j)
   self.call('writing.prepare');self.assertNotEqual(m.context(e,'Test')['id'],round_id);self.assertFalse((self.path/'retrieval/keep.json').exists())
 def test_mutating_round_actions_respect_project_job_ownership(self):
  import library_service
  with patch.object(library_service,'check_owner',side_effect=ValueError('Zotero 导入正在运行')):
   for action in ('review.writing.prepare.resume','review.writing.reset'):
    with self.subTest(action=action),self.assertRaisesRegex(ValueError,'Zotero'):
     e.rpc(action,{'project':'test','name':'Test','confirm':True})
 def test_reset_rejects_symlinks_and_preserves_other_workspace(self):
  self.seed();other=r.rpc(e,'create',{'name':'Other','outlineSource':'workspace','sourceWorkspace':'Test'})
  outside=e.ROOT/'keep.txt';outside.write_text('untouched');(self.path/'sections/link').symlink_to(outside)
  with self.assertRaisesRegex(ValueError,'符号链接'):self.call('writing.reset',confirm=True)
  self.assertEqual(outside.read_text(),'untouched');self.assertTrue((self.path/'sections').exists())
  (self.path/'sections/link').unlink();self.call('writing.reset',confirm=True)
  self.assertEqual(r.rpc(e,'get',{'name':'Other'})['rows'],other['rows'])
 def test_preflight_failure_preserves_body_and_active_jobs_block_reset(self):
  self.seed()
  with self.assertRaisesRegex(ValueError,'Embedding'):self.call('writing.prepare',confirm=True)
  self.assertTrue((self.path/'sections').exists())
  e.write_json(self.path/'writing-job.json',{'state':'running','pid':os.getpid()})
  with self.assertRaisesRegex(ValueError,'撰写'):self.call('writing.reset',confirm=True)

if __name__=='__main__':unittest.main()
