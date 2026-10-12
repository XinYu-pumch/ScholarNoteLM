import asyncio,base64,gzip,hashlib,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,reader_service as r,storage
import test_scihub_retry as fixtures

class ReaderTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test';self.base=storage.project_dir(e.ROOT,e.PROJECT);self.xml()
  self.profile={'id':'p','model':'fixture','endpoint':'http://127.0.0.1:1/v1/chat/completions'}
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def xml(self,text='ABSTRACT_ONLY',ids=('1','2')):
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>Study {p}</ArticleTitle><Abstract><AbstractText>{text}</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for p in ids)+'</PubmedArticleSet>')
 def raw(self,text='UNCLEANED_FULLTEXT\n# References\nReferences retained'):
  pdf=fixtures.pdf();e.atomic(self.base/'pdf/1.pdf',pdf);e.atomic(self.base/'markdown/raw/1.md',text);e.atomic(self.base/'markdown/1.md','CLEANED_TEXT_NEVER_SEND')
  e.write_json(self.base/'metadata/markdown/1.json',{'pdfSha256':hashlib.sha256(pdf).hexdigest(),'rawSha256':hashlib.sha256(text.encode()).hexdigest()})
 def new(self,p='1'):return r.rpc(e,'new',{'pmid':p})
 def start(self,t,**a):
  with patch.object(r.review_service,'profile',return_value=self.profile),patch.object(r.subprocess,'Popen'):
   return r.rpc(e,'start',{'id':t['id'],'question':'Question',**a})
 def finish(self,t):
  with r.db(e) as c:t=r.get(c,t['id']);t['state']='done';t['messages'][-1].update(text='Answer',state='done');r.put(c,t)
  return t
 def test_abstract_without_pdf_and_full_raw_with_pdf(self):
  d=r.document(e,'1');self.assertEqual(d['kind'],'abstract');self.assertIn('ABSTRACT_ONLY',d['text'])
  self.raw();d=r.document(e,'1');self.assertTrue(d['ready']);self.assertIn('References retained',d['text']);self.assertNotIn('CLEANED_TEXT',d['text'])
 def test_missing_raw_and_stale_pdf_block_start(self):
  self.raw();(self.base/'markdown/raw/1.md').unlink();self.assertFalse(r.document(e,'1')['ready'])
  with self.assertRaisesRegex(ValueError,'转换'):self.start(self.new())
  self.raw();e.atomic(self.base/'pdf/1.pdf',fixtures.pdf().replace(b'100',b'101'));self.assertFalse(r.document(e,'1')['ready'])
 def test_raw_mutation_invalidates_source(self):
  self.raw();e.atomic(self.base/'markdown/raw/1.md','Changed');self.assertFalse(r.document(e,'1')['ready'])
 def test_shared_snapshot_pin_and_garbage_collection(self):
  self.raw();a=self.finish(self.start(self.new()));b=self.finish(self.start(self.new()));self.assertEqual(a['source'],b['source']);self.assertEqual(len(list(r.safe(e,'sources').glob('*.gz'))),1)
  self.raw('NEW_VERSION');a2=self.finish(self.start(a));c=self.finish(self.start(self.new()));self.assertEqual(a['source'],a2['source']);self.assertNotEqual(a['source'],c['source'])
  r.rpc(e,'delete',{'id':a['id']});self.assertEqual(len(list(r.safe(e,'sources').glob('*.gz'))),2)
  r.rpc(e,'delete',{'id':b['id']});self.assertEqual(len(list(r.safe(e,'sources').glob('*.gz'))),1)
  raw=gzip.decompress(next(r.safe(e,'sources').glob('*.gz')).read_bytes());self.assertIn(b'NEW_VERSION',raw)
 def test_unknown_pmid_and_cross_project_thread_rejected(self):
  with self.assertRaisesRegex(ValueError,'不在'):self.new('99')
  t=self.new();e.PROJECT='other'
  with self.assertRaisesRegex(ValueError,'不存在'):r.rpc(e,'get',{'id':t['id']})
 def test_per_paper_conversations_and_progress(self):
  a=self.new();b=self.new('2');self.assertEqual([x['id'] for x in r.rpc(e,'list',{'pmid':'1'})['threads']],[a['id']])
  r.rpc(e,'progress',{'pmid':'1','value':{'page':3,'thread':a['id']}});r.rpc(e,'progress',{'pmid':'1','value':{'zoom':'fit'}})
  self.assertEqual(r.rpc(e,'progress',{'pmid':'1'})['page'],3);self.assertEqual(r.rpc(e,'recent',{})['items'][0]['pmid'],'1')
 def test_duplicate_start_delete_and_retry_in_place(self):
  t=self.start(self.new())
  with self.assertRaisesRegex(ValueError,'正在生成'):self.start(t)
  with self.assertRaisesRegex(ValueError,'先停止'):r.rpc(e,'delete',{'id':t['id']})
  t=self.finish(t);t=self.start(t,retry=True);self.assertEqual(len(t['messages']),1)
 def test_removed_article_cannot_start_even_with_pinned_source(self):
  t=self.finish(self.start(self.new()));self.xml(ids=('2',))
  with self.assertRaisesRegex(ValueError,'不在'):self.start(t)
 def test_pdf_chunk_and_version_guard(self):
  self.raw();d=r.document(e,'1');data=r.rpc(e,'pdf',{'pmid':'1','version':d['pdfVersion']});self.assertEqual(base64.b64decode(data['data']),fixtures.pdf())
  with self.assertRaisesRegex(ValueError,'变化'):r.rpc(e,'pdf',{'pmid':'1','version':'wrong'})
 def test_symlink_raw_rejected(self):
  self.raw();path=self.base/'markdown/raw/1.md';path.unlink();path.symlink_to(self.base/'markdown/1.md')
  with self.assertRaises(ValueError):r.document(e,'1')
 def test_snapshot_corruption_rejected(self):
  t=self.finish(self.start(self.new()));e.atomic(r.safe(e,'sources',t['source']+'.json.gz'),gzip.compress(b'{}'))
  with self.assertRaisesRegex(ValueError,'校验失败'):self.start(t)
 def test_crashed_worker_is_recoverable(self):
  t=self.start(self.new())
  with r.db(e) as c:t=r.get(c,t['id']);t['updated']=time.time()-60;c.execute('UPDATE threads SET data=? WHERE id=?',(json.dumps(t),t['id']))
  t=r.rpc(e,'get',{'id':t['id']});self.assertEqual(t['state'],'failed');self.assertIn('中断',t['error']);self.assertEqual(r.jobs(e),[])
 def test_worker_sends_full_source_and_only_successful_history(self):
  self.raw('FULL_BEGIN\n'+'evidence '*20000+'\nFULL_END\nReferences retained');t=self.finish(self.start(self.new()));t=self.start(t,question='Follow-up');seen=[]
  async def chat(profile,messages,**kw):seen.extend(messages);kw['on_text']('New answer');return 'New answer'
  import review_llm
  with patch.object(r.review_service,'profile',return_value=self.profile),patch.object(review_llm,'chat',side_effect=chat):asyncio.run(r.run(e,t['id'],t['run']))
  self.assertIn('FULL_END',seen[1]['content']);self.assertIn('References retained',seen[1]['content']);self.assertEqual([m['content'] for m in seen[2:]],['Question','Answer','Follow-up'])
  final=r.rpc(e,'get',{'id':t['id']});self.assertEqual(final['state'],'done');self.assertEqual(final['messages'][-1]['text'],'New answer');self.assertNotIn('FULL_BEGIN',r.safe(e,'reader.sqlite3').read_bytes().decode(errors='ignore'))
 def test_cancel_before_worker_preserves_question_and_skips_model(self):
  t=self.start(self.new());r.rpc(e,'cancel',{'id':t['id']})
  import review_llm
  with patch.object(review_llm,'chat') as chat:asyncio.run(r.run(e,t['id'],t['run']));chat.assert_not_called()
  self.assertEqual(r.rpc(e,'get',{'id':t['id']})['state'],'cancelled')
 def test_old_worker_cannot_overwrite_new_run(self):
  t=self.start(self.new());asyncio.run(r.run(e,t['id'],'wrong'));self.assertEqual(r.rpc(e,'get',{'id':t['id']})['state'],'queued')

 def test_fork_copies_prefix_and_shares_source_after_parent_delete(self):
  self.raw();t=self.finish(self.start(self.new()));first=t['messages'][0]['id'];t=self.finish(self.start(t,question='Second'))
  child=r.rpc(e,'fork',{'id':t['id'],'turnId':first})
  self.assertEqual(len(child['messages']),1);self.assertEqual(child['parentId'],t['id']);self.assertEqual(child['source'],t['source'])
  self.assertNotIn('run',child);self.assertEqual(child['state'],'idle')
  r.rpc(e,'delete',{'id':t['id']});self.assertIn('UNCLEANED_FULLTEXT',r.load_source(e,child['source'])['text'])
  child=self.start(child,question='Branch follow-up');self.assertEqual(len(child['messages']),2)
 def test_historical_regeneration_preserves_original_and_omits_later_turns(self):
  t=self.finish(self.start(self.new()));t=self.finish(self.start(t,question='Second'));original=r.rpc(e,'get',{'id':t['id']})
  result=self.start(t,retry=True,turnId=t['messages'][0]['id'])
  self.assertNotEqual(result['id'],t['id']);self.assertEqual(len(result['messages']),1);self.assertEqual(result['messages'][0]['question'],'Question')
  self.assertNotEqual(result['messages'][0]['id'],t['messages'][0]['id']);self.assertEqual(r.rpc(e,'get',{'id':t['id']}),original)
 def test_latest_regeneration_rejects_stale_turn_id(self):
  t=self.finish(self.start(self.new()));old=t['messages'][0]['id'];fresh=self.finish(self.start(t,retry=True,turnId=old))
  self.assertEqual(t['id'],fresh['id']);self.assertNotEqual(fresh['messages'][0]['id'],old)
  with self.assertRaisesRegex(ValueError,'已变化'):self.start(fresh,retry=True,turnId=old)
  with self.assertRaisesRegex(ValueError,'已变化'):r.rpc(e,'fork',{'id':fresh['id'],'turnId':old})
 def test_fork_only_completed_turn_while_parent_can_keep_running(self):
  t=self.finish(self.start(self.new()));first=t['messages'][0]['id'];t=self.start(t,question='Pending')
  with self.assertRaisesRegex(ValueError,'完成'):r.rpc(e,'fork',{'id':t['id'],'turnId':t['messages'][-1]['id']})
  child=r.rpc(e,'fork',{'id':t['id'],'turnId':first});self.assertEqual(child['state'],'idle');self.assertEqual(r.rpc(e,'get',{'id':t['id']})['state'],'queued')
 def test_legacy_message_ids_are_stable_without_storage_migration(self):
  t=self.finish(self.start(self.new()))
  with r.db(e) as c:
   t['messages'][0].pop('id');r.put(c,t)
  first=r.rpc(e,'get',{'id':t['id']})['messages'][0]['id']
  self.assertEqual(first,r.rpc(e,'get',{'id':t['id']})['messages'][0]['id'])
  self.assertEqual(r.rpc(e,'fork',{'id':t['id'],'turnId':first})['messages'][0]['id'],first)

if __name__=='__main__':unittest.main()
