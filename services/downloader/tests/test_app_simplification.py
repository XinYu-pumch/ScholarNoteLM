"""Migration, fixed conversion, and embedding-only contracts, without remote calls."""
import asyncio,base64,copy,json,sys,unittest,zlib,struct
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,markdown_service as m,embedding_profiles as profiles,vector_service as v,retrieval_settings,embedding_limits,review_retrieval,review_llm
import cleaning_fixture as fixture

class SimplificationTests(unittest.TestCase):
 setUp=fixture.CleaningIntegrationTests.setUp
 tearDown=fixture.CleaningIntegrationTests.tearDown
 job=fixture.CleaningIntegrationTests.job
 def test_cleaning_is_fixed_and_keeps_source_positions(self):
  text='# Title\n\nShort.\n\n- Useful list\n\nFunding: none.\n\n'+fixture.WATERMARK+'\n\n# References\n\n1. Smith AB, Jones CD. Study title. Journal. 2020;12:10-20.\n\n2. Wilson EF, Martin GH. Second title. Journal. 2021;13:30-40.\n'
  cleaned,removed=m.clean(text,{'badrCleanup':False,'cleaningMode':'legacy-badr','removeLines':['Short']})
  self.assertTrue(removed);self.assertNotIn('Smith AB',cleaned)
  for keep in ('# Title','Short.','- Useful list','Funding: none.',fixture.WATERMARK):self.assertIn(keep,cleaned)
  for row in removed:self.assertEqual(text[row['charStart']:row['charEnd']],row['text'])
 def test_existing_marker_signature_survives_and_removed_settings_cannot_reactivate(self):
  import hashlib,markdown_cleaning
  cfg=dict(m.DEFAULTS);expected=hashlib.sha256(json.dumps({**{k:v for k,v in cfg.items() if k!='pdftextWorkers'},'cleaningVersion':'references-only-v2','paragraphVersion':markdown_cleaning.PARAGRAPH_VERSION},sort_keys=True).encode()).hexdigest()
  self.assertEqual(m.signature(m.config(e)),expected)
  e.write_json(self.base/'metadata/conversion-settings.json',{'engine':'paddleocr','badrCleanup':False,'cleaningMode':'body-first-v1','device':'cpu'})
  before=(self.base/'markdown/1.md').read_bytes();cfg=m.config(e)
  self.assertEqual(cfg['engine'],'marker');self.assertTrue(cfg['badrCleanup']);self.assertEqual(cfg['cleaningMode'],'references-v1');self.assertEqual(cfg['device'],'cpu')
  self.assertEqual((self.base/'markdown/1.md').read_bytes(),before)
 def test_real_clean_worker_preserves_raw_history_and_updates_provenance(self):
  raw=(self.base/'markdown/raw/1.md').read_bytes();job,report=self.job('fixed-clean')
  self.assertEqual(job['completed'],1,job['items']);self.assertEqual((self.base/'markdown/raw/1.md').read_bytes(),raw)
  self.assertTrue((self.base/'markdown/history/1/fixed-clean/1.md').exists())
  meta=json.loads((self.base/'metadata/markdown/1.json').read_text());self.assertEqual(meta['engine'],'Marker 1.6.0');self.assertEqual(meta['cleaningVersion'],'references-only-v2')
  self.assertIn(fixture.NOTICE,(self.base/'markdown/1.md').read_text())
 def test_short_heading_filter_and_no_metadata_embedding(self):
  rows=[{'id':'short','text':'# Topic','metadata':{'blockType':'heading'}},{'id':'long','text':'# '+('Useful evidence '*12),'metadata':{'blockType':'heading'}},{'id':'caption','text':'Short caption.','metadata':{'blockType':'caption'}},{'id':'body','text':'Measured result.','metadata':{'blockType':'paragraph','title':'Do not embed title'}}]
  with patch.object(review_retrieval,'APIRecall') as recall:
   recall.return_value.recall.return_value=[(0,.9),(1,.8),(2,.7)]
   r=review_retrieval.Retriever(e.ROOT,None,rows,lambda:None,lambda _:None,{},e)
   self.assertEqual([x['id'] for x in r.retrieve('Question',50,3)],['long','caption','body']);recall.return_value.recall.assert_called_once_with('Question',3)
  from vector_chunks import embedding_text
  self.assertEqual(embedding_text(rows[-1]),'Measured result.')
 def test_image_test_sends_real_png_and_requires_matching_answer(self):
  seen=[]
  async def chat(profile,messages,*a,**kw):seen.append(messages);return 'blue'
  with patch('secrets.choice',return_value=('blue',(0,0,255))),patch.object(review_llm,'chat',side_effect=chat):result=asyncio.run(review_llm.test_connection({'baseUrl':'https://example.test/v1','model':'test','testVision':True}))
  self.assertTrue(result['imageVerified']);data=base64.b64decode(seen[0][0]['content'][1]['image_url']['url'].split(',')[1]);self.assertTrue(data.startswith(b'\x89PNG'))
  with patch('secrets.choice',return_value=('red',(255,0,0))),patch.object(review_llm,'chat',side_effect=chat),self.assertRaisesRegex(ValueError,'未通过'):asyncio.run(review_llm.test_connection({'baseUrl':'https://example.test/v1','model':'test','testVision':True}))
if __name__=='__main__':unittest.main()
