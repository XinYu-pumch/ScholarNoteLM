"""Language snapshots must not translate evidence or invalidate legacy work."""
import asyncio,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import content_language as lang,engine as e,review_service as reviews,review_writing as writing,reader_service as reader,review_llm,qa_service as qa
from test_review import ReviewTests
from test_reader import ReaderTests
from test_qa_retry import RetryTests

class ReviewLanguageTests(ReviewTests):
 def test_workspace_language_template_and_legacy_config(self):
  self.create()
  before=writing.config(reviews.work(e,'Review1'))
  self.assertNotIn('promptVersion',before)
  created=self.call('create',name='English',contentLanguage='en',templateWorkspace='Review1')
  self.assertEqual(created['workspace']['contentLanguage'],'en');self.assertEqual(created['version']['topic'],'免疫');self.assertEqual(created['rows'],[])
  cfg=writing.config(reviews.work(e,'English'));self.assertEqual(cfg['language'],'English');self.assertEqual(cfg['promptVersion'],lang.VERSION)
  preview=self.call('prompt',name='English',topic='免疫',requirements='保留源文献')
  self.assertIn(lang.OUTLINE_SYSTEM_EN,preview['content']);self.assertIn('保留源文献',preview['content']);self.assertIn('Evidence {literal}',preview['content']);self.assertNotIn('【系统提示词】',preview['content'])
  self.assertEqual(writing.config(reviews.work(e,'Review1')),before)
  self.call('language',name='English',contentLanguage='zh')
  self.call('import',name='English',revision=0,csv='1,Introduction\n')
  with self.assertRaises(ValueError):self.call('language',name='English',contentLanguage='en')

class ExportLanguageTests(unittest.TestCase):
 def test_english_labels_preserve_source_text(self):
  import review_export,review_manuscripts
  from bs4 import BeautifulSoup
  rows=[{'serial':'1','title':'原始标题'}]
  html=review_export.html_document('综述主题',rows,{'1':'原始证据 (PMID: 123)'},{'1':{'123':['原始证据']}},False,language='en')
  soup=BeautifulSoup(html,'html.parser')
  self.assertEqual(soup.html['lang'],'en');self.assertEqual(soup.find(id='toggle-ref').get_text(),'Citation details')
  self.assertIn('原始标题',soup.get_text());self.assertIn('原始证据',soup.get_text())
  self.assertFalse(soup.select('script[src],link[rel=stylesheet]'))

class ReaderLanguageTests(ReaderTests):
 def test_inflight_retry_and_branch_pin_language(self):
  self.raw('全文保持不变 References')
  t=reader.rpc(e,'new',{'pmid':'1','contentLanguage':'en'});t=self.start(t)
  reader.rpc(e,'language',{'id':t['id'],'contentLanguage':'zh'})
  seen=[]
  async def chat(profile,messages,**kw):seen.extend(messages);return 'English answer'
  with patch.object(reader.review_service,'profile',return_value=self.profile),patch.object(review_llm,'chat',side_effect=chat):asyncio.run(reader.run(e,t['id'],t['run']))
  self.assertIn(lang.READER_EN,seen[0]['content']);self.assertIn('全文保持不变',seen[1]['content'])
  done=reader.rpc(e,'get',{'id':t['id']});self.assertEqual(done['contentLanguage'],'zh')
  branch=reader.rpc(e,'fork',{'id':t['id'],'turnId':done['messages'][0]['id']});self.assertEqual(branch['contentLanguage'],'en')
  retried=self.start(done,retry=True);self.assertEqual(retried['messages'][-1]['contentLanguage'],'en')

class QALanguageTests(RetryTests):
 def test_retry_and_branch_keep_original_language(self):
  qa.rpc(e,'language',{'threadId':self.t['id'],'contentLanguage':'en'})
  rid=self.add('Original English','failed')
  qa.rpc(e,'language',{'threadId':self.t['id'],'contentLanguage':'zh'})
  branch=qa.rpc(e,'fork',{'threadId':self.t['id'],'keepCount':1});self.assertEqual(branch['contentLanguage'],'en')
  retried=qa.rpc(e,'regenerate',{'threadId':self.t['id'],'runId':rid});self.assertEqual(qa.read(qa.runpath(e,retried['id'])/'input.json')['contentLanguage'],'en')
 def test_legacy_resume_preserves_prompt_protocol(self):
  rid=self.add('Legacy','failed');path=qa.runpath(e,rid)
  for name in ('input.json','job.json'):
   obj=qa.read(path/name);obj.pop('promptVersion');obj.pop('contentLanguage');e.write_json(path/name,obj)
  resumed=qa.rpc(e,'resume',{'threadId':self.t['id'],'runId':rid})
  snapshot=qa.read(qa.runpath(e,resumed['id'])/'input.json');self.assertIsNone(snapshot['promptVersion']);self.assertEqual(snapshot['contentLanguage'],'zh')

# Reuse fixtures without rerunning their inherited test methods.
for cls,base in ((ReviewLanguageTests,ReviewTests),(ReaderLanguageTests,ReaderTests),(QALanguageTests,RetryTests)):
 for key in dir(base):
  if key.startswith('test_') and key not in cls.__dict__:setattr(cls,key,None)
del ReviewTests,ReaderTests,RetryTests,cls,base
if __name__=='__main__':unittest.main()
