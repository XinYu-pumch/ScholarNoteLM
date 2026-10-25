import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,review_service as r,storage

class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.old=(e.ROOT,e.PROJECT);self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test';self.base=storage.project_dir(e.ROOT,e.PROJECT)
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>Nested <i>title</i></ArticleTitle><Abstract><AbstractText Label="RESULTS">Evidence {literal}</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle><PubmedArticle><MedlineCitation><PMID>2</PMID><Article><ArticleTitle>No abstract</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def call(self,op,**a):return r.rpc(e,op,{'name':'Review1',**a})
 def create(self):return self.call('create',description='目标',topic='免疫')
 def test_obsolete_project_lock_does_not_block_workspaces(self):
  with storage.file_lock(self.base/'metadata/reviews.lock'):
   self.create()
   self.call('create',name='Independent',topic='Other')
   self.assertEqual(self.call('get')['workspace']['name'],'Review1')
   self.assertEqual({v['name'] for v in self.call('list')['workspaces']},{'Review1','Independent'})
 def test_outline_cancel_survives_stale_progress_write(self):
  import review_llm
  self.create();path=r.work(e,'Review1');token='cancel-race'
  state=r.read(path/'outline-state.json');state.update(state='queued',token=token,profileId='p',model='m')
  e.write_json(path/'outline-state.json',state);e.write_json(path/'prompt.json',{'system':'fixture','user':'fixture'})
  e.atomic(path/'outline.csv','1,Original\n');write=e.write_json;injected=[]
  def racing_write(target,value):
   if target==path/'outline-state.json' and value.get('reasoningCharacters')==12 and value.get('state')=='running' and not injected:
    injected.append(True)
    self.assertEqual(self.call('cancel')['version']['state'],'stopping')
   write(target,value)
  async def chat(profile,messages,cancelled,progress,on_text):
   progress(received=0,reasoningCharacters=12)
   self.assertTrue(cancelled())
   on_text('1,Must not publish\n')
  with patch.object(e,'write_json',side_effect=racing_write),patch.object(r,'profile',return_value={'model':'m'}),patch.object(r.llm_provider,'adapter',return_value=object()),patch.object(review_llm,'chat',side_effect=chat):
   r.worker(e,'Review1','current',token)
  self.assertTrue(injected);self.assertEqual(r.read(path/'outline-state.json')['state'],'cancelled')
  self.assertEqual((path/'outline.csv').read_text(),'1,Original\n')
  self.assertTrue(r.cancel_requested(path,'outline',token))
  self.assertFalse(r.cancel_requested(path,'outline','new-run'))
 def test_outline_publishes_reasoning_progress_before_answer_callback(self):
  import review_llm
  self.create();path=r.work(e,'Review1');token='thinking-progress'
  state=r.read(path/'outline-state.json');state.update(state='queued',token=token,profileId='p',model='m')
  e.write_json(path/'outline-state.json',state);e.write_json(path/'prompt.json',{'system':'fixture','user':'fixture'})
  observed=[]
  async def chat(profile,messages,cancelled,progress,on_text):
   progress(received=0,reasoningCharacters=12)
   observed.append(r.read(path/'outline-state.json'))
   on_text('Serial,Title\n1,结果\n')
  with patch.object(r,'profile',return_value={'model':'m'}),patch.object(r.llm_provider,'adapter',return_value=object()),patch.object(review_llm,'chat',side_effect=chat):
   r.worker(e,'Review1','current',token)
  self.assertEqual(observed[0]['reasoningCharacters'],12);self.assertEqual(observed[0]['received'],0)
  self.assertEqual(r.read(path/'outline-state.json')['state'],'done')
 def test_generation_pins_explicit_model_from_pool(self):
  self.create()
  with patch.object(r,'profile',return_value={'id':'provider-b','model':'chosen-model','name':'B'}) as resolve, patch.object(r.subprocess,'Popen') as child:
   child.return_value.pid=123
   with patch.object(e,'process_alive',return_value=True):
    result=self.call('start',revision=0,topic='免疫',profileId='provider-b',model='chosen-model')
   resolve.assert_called_once_with(e,'provider-b','chosen-model')
  self.assertEqual(result['version']['profileId'],'provider-b');self.assertEqual(result['version']['model'],'chosen-model')
 def test_start_does_not_overwrite_worker_progress(self):
  import os
  self.create();path=r.work(e,'Review1')/'outline-state.json'
  def spawned(*args,**kwargs):
   state=r.read(path);state.update(state='running',pid=os.getpid(),reasoningCharacters=42);e.write_json(path,state)
  with patch.object(r,'profile',return_value={'id':'p','model':'m'}),patch.object(r.subprocess,'Popen',side_effect=spawned):
   result=self.call('start',revision=0,topic='Review')
  self.assertEqual(result['version']['state'],'running')
  self.assertEqual(result['version']['pid'],os.getpid())
  self.assertEqual(result['version']['reasoningCharacters'],42)
 def test_worker_that_exits_before_registering_can_be_restarted(self):
  import time
  self.create();path=r.work(e,'Review1')/'outline-state.json'
  state=r.read(path);state.update(state='queued',pid=0,updated=time.time()-40);e.write_json(path,state)
  self.assertEqual(self.call('get')['version']['state'],'failed')
 def test_csv_all_levels_and_quotes(self):
  rows=r.parse_csv('\ufeff```csv\nSerial,Title\n1,引言\n1.1,"背景,机制"\n1.1.1,"作用与""边界"""\n1.2,问题\n2,结论\n```')
  self.assertEqual(len(rows),5);self.assertEqual(rows[1]['title'],'背景,机制');self.assertEqual(r.parse_csv(r.to_csv(rows)),rows)
 def test_outline_depth_is_not_limited_to_six(self):
  text='Serial,Title\n'+'\n'.join('.'.join(['1']*level)+f',第 {level} 层' for level in range(1,65))
  rows=r.parse_csv(text);self.assertEqual(len(rows),64);self.assertEqual(len(rows[-1]['serial'].split('.')),64)
  self.assertNotIn('最多六级',r.SYSTEM)
 def test_csv_rejects_broken_structure_without_silent_dropping(self):
  bad=['','1,','1,a\n1,b','1,a\n1.2,b','1.1,a','2,a','01,a','1,a\n3,b','1,a\n2,b\n1.1,c','1,a,extra','1,"unclosed','1,"line\nbreak"','1,a\nthis is not csv','1,a\n1.1,b\n1.1.1,c\n1.2,d\n1.1.2,e']
  for text in bad:
   with self.subTest(text=text),self.assertRaises(ValueError):r.parse_csv(text)
 def test_large_outline_import_and_save_without_truncation(self):
  self.create()
  rows=[{'serial':str(i),'title':'标题'*110} for i in range(1,10002)]
  rows[0]['title']='长标题'*50000
  text=r.to_csv(rows);self.assertGreater(len(text),2_000_000)
  imported=self.call('import',revision=0,csv=text)
  self.assertEqual([(x['serial'],x['title']) for x in imported['rows']],[(x['serial'],x['title']) for x in rows])
  saved=self.call('save',revision=imported['version']['revision'],rows=imported['rows'])
  self.assertEqual(saved['rows'],imported['rows'])
 def test_filename_validation_case_collision_and_windows(self):
  for name in ('../bad','a-b','a/b','a\\b','a b','a.','CON','nul','a'*65):
   with self.subTest(name=name),self.assertRaises(ValueError):self.call('create',name=name)
  self.create()
  with self.assertRaises(ValueError):self.call('create',name='review1')
 def test_chinese_and_underscore_names_list_copy_and_export(self):
  name='肠道免疫_Review2026'
  self.call('create',name=name,outlineSource='file',csv='1,引言\n')
  self.assertTrue((self.base/'review'/name/'outline.csv').exists())
  self.assertIn(name,[w['name'] for w in self.call('list')['workspaces']])
  copied=self.call('create',name='独立_副本',outlineSource='workspace',sourceWorkspace=name)
  self.assertEqual(copied['rows'][0]['title'],'引言')
  result=self.call('export',name=name,revision=0,rows=self.call('get',name=name)['rows'])
  self.assertTrue(Path(result['path']).is_file())
 def test_workspace_has_one_current_outline(self):
  d=self.create();self.assertEqual(d['version']['id'],'current')
  self.assertTrue((self.base/'review/Review1/outline-state.json').exists())
 def test_save_validate_restore_and_revision_conflict(self):
  self.create();vp=r.version(e,'Review1','v0001');original='Serial,Title\n1,原始\n1.1,机制\n';e.atomic(vp/'generated.csv',original);e.atomic(vp/'outline.csv',original)
  d=self.call('save',version='v0001',revision=0,topic='免疫',rows=[{'serial':'1','title':'修改后'}]);self.assertEqual(d['rows'][0]['title'],'修改后')
  with self.assertRaises(ValueError):self.call('save',revision=0,rows=[{'serial':'1','title':'冲突'}])
  with self.assertRaises(ValueError):self.call('import',revision=1,csv='1.1,无父标题')
  self.assertEqual(self.call('get')['rows'][0]['title'],'修改后')
  d=self.call('restore',revision=1);self.assertEqual(len(d['rows']),2);self.assertEqual((vp/'generated.csv').read_text(),original)
 def test_full_prompt_export_no_model_needed_and_no_truncation(self):
  self.create();result=self.call('prompt',topic='主题 {x}',requirements='请关注 {y}')
  text=Path(result['path']).read_text();self.assertIn('主题 {x}',text);self.assertIn('请关注 {y}',text);self.assertIn('Nested title',text);self.assertIn('Evidence {literal}',text);self.assertIn(r.SYSTEM,text)
  self.assertEqual(result['abstractCount'],1);self.assertEqual(self.call('get')['version']['state'],'draft')
 def test_csv_import_preserves_form_inputs_and_generation_baseline(self):
  self.create();vp=r.version(e,'Review1','v0001');e.atomic(vp/'generated.csv','1,原稿\n')
  d=self.call('import',revision=0,csv='1,外部编辑稿\n',topic='新主题',requirements='新要求')
  self.assertEqual(d['version']['topic'],'新主题');self.assertEqual(d['version']['requirements'],'新要求')
  self.assertEqual((vp/'generated.csv').read_text(),'1,原稿\n')
  exported=self.call('export',revision=d['version']['revision'],rows=d['rows'])
  self.assertEqual(Path(exported['path']).read_text(encoding='utf-8-sig'),exported['content'])
 def test_abstracts_and_xml_errors(self):
  _,text,s=r.abstracts(e);self.assertEqual((s['total'],s['abstractCount'],s['missingAbstracts']),(2,1,1));self.assertIn('PMID: 1',text)
  e.atomic(self.base/'pubmed/current.xml','<broken>')
  with self.assertRaises(ValueError):r.abstracts(e)
 def test_delete_permanently_removes_workspace_and_preserves_others(self):
  self.create()
  with self.assertRaises(ValueError):self.call('delete',confirm='other')
  self.call('create',name='其他_综述')
  path=r.work(e,'Review1');e.atomic(path/'manuscripts/saved/document.json','saved');e.atomic(path/'exports/review.md','exported')
  (path/'outside-link').symlink_to(r.work(e,'其他_综述'),target_is_directory=True)
  self.call('delete',confirm='Review1');self.assertFalse(path.exists());self.assertFalse((self.base/'metadata/review-trash').exists())
  self.assertTrue((r.work(e,'其他_综述')/'review.json').exists())
 def test_active_generation_prevents_save_delete_and_restore(self):
  self.create();vp=r.version(e,'Review1','v0001');v=r.read(vp/'outline-state.json');v.update(state='running');e.write_json(vp/'outline-state.json',v)
  for op in ('save','restore','delete'):
   with self.subTest(op=op),self.assertRaises(ValueError):self.call(op,revision=0,confirm='Review1')
  self.call('cancel');self.assertEqual(self.call('get')['version']['state'],'stopping')
 def test_symlink_workspace_rejected(self):
  r.root(e).mkdir(parents=True);outside=e.ROOT/'outside';outside.mkdir();(r.root(e)/'Review1').symlink_to(outside,target_is_directory=True)
  with self.assertRaises(ValueError):self.call('get')
 def test_regeneration_validates_before_replacing_outline(self):
  self.create();vp=r.version(e,'Review1','current');e.atomic(vp/'generated.csv','1,original');e.atomic(vp/'outline.csv','1,edited')
  with self.assertRaisesRegex(ValueError,'配置'):self.call('start',revision=0,topic='new')
  self.assertEqual((vp/'outline.csv').read_text(),'1,edited');self.assertEqual((vp/'generated.csv').read_text(),'1,original')
if __name__=='__main__':unittest.main()
