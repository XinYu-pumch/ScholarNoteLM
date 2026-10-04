import base64,hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import evidence_resources as res,vector_chunks as chunks,markdown_service as clean,qa_service as qa,review_format,review_writing,review_service
import cleaning_fixture as fixture
import engine as e,corpus_files as files,artifact_state
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jX1sAAAAASUVORK5CYII=')
REF='# References\n\n1. Smith AB, Jones CD. Study title. Journal. 2020;12:10-20.\n\n2. Wilson EF, Martin GH. Second title. Journal. 2021;13:30-40.\n'

class ResourceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.asset=self.root/'markdown/assets/1/figure.png';self.asset.parent.mkdir(parents=True);self.asset.write_bytes(PNG)
 def tearDown(self):self.temp.cleanup()
 def extract(self,text):
  segments=chunks.split(text)
  def save(path,data):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
  return res.extract(self.root,'1','v',text,segments,save),segments
 def test_references_only_and_short_text_included(self):
  text='# Title\n\nShort caption.\n\nFunding: None.\n\n'+fixture.NOTICE+'\n\n'+REF
  out,removed=clean.clean(text,clean.DEFAULTS)
  for value in ['# Title','Short caption.','Funding: None.',fixture.NOTICE]:self.assertIn(value,out)
  self.assertNotIn('Smith AB',out);self.assertTrue(all(s['ruleId']=='R01_references' for s in removed))
  segments=chunks.split(out);self.assertTrue(all(s['accepted'] for s in segments));self.assertTrue(any(s['text']=='Short caption.' for s in segments))
  for s in segments:
   self.assertEqual(qa.evidence_allowed({'text':s['text'],'metadata':s}),s['blockType']!='heading')
 def test_reference_only_keeps_article_citation_fallback_but_not_metadata_rules(self):
  from cleaning_fixture import CITE,SCIENCE,WATERMARK
  raw='# Citation\n\n'+CITE+'\n\n# Results\n\n'+SCIENCE+'\n\n'+WATERMARK+'\n\nFunding: None.'
  out,removed=clean.clean(raw,clean.DEFAULTS)
  self.assertNotIn(CITE,out);self.assertIn(SCIENCE,out);self.assertIn(WATERMARK,out);self.assertIn('Funding: None.',out)
  self.assertTrue(any(s['reason']=='complete_article_citation' for s in removed))
  mixed='# Citation\n\n'+CITE+' '+SCIENCE
  self.assertEqual(clean.clean(mixed,clean.DEFAULTS),(mixed,[]))
 def test_long_table_keeps_normal_chunks_and_whole_object(self):
  table='| Gene | Value |\n|---|---|\n'+''.join(f'| G{i} | {i}.50 |\n' for i in range(1500))
  text='Before.\n\n'+table+'\nAfter.\n\nFarther.\n\nUnrelated.'
  objects,segments=self.extract(text);self.assertEqual(len(objects),1);obj=objects[0];self.assertEqual(obj['content'],table)
  overlapping=[s for s in segments if s['charStart']<obj['charEnd'] and s['charEnd']>obj['charStart']]
  self.assertGreater(len(overlapping),1);self.assertTrue(all(s['chunkIndex'] in obj['chunkIndices'] for s in overlapping))
  self.assertEqual([p['content'].strip() for p in obj['context']],['Before.','After.','Farther.'])
  self.assertNotIn(segments[-1]['chunkIndex'],obj['chunkIndices'])
 def test_positions_no_names_required_and_short_context(self):
  text='😀 first\r\n\r\nTiny.\r\n\r\n![](assets/1/figure.png)\r\n\r\nUnnamed explanation.\r\n\r\nLast.\r\n'
  objects,segments=self.extract(text);obj=objects[0]
  self.assertEqual(text[obj['charStart']:obj['charEnd']],obj['content']);self.assertEqual(obj['lineStart'],5)
  self.assertEqual(len(obj['context']),4);self.assertTrue(all(s['chunkIndex'] in obj['chunkIndices'] for s in segments))
  self.assertTrue(res.image_data(self.root,obj).startswith('data:image/png;base64,'))
  first=res.fingerprint(self.root,'1',text);self.asset.write_bytes(PNG+b'changed')
  self.assertNotEqual(first,res.fingerprint(self.root,'1',text));self.assertEqual(base64.b64decode(res.image_data(self.root,obj).split(',')[1]),PNG)
 def test_images_only_for_selected_vision_model_and_deduplicated(self):
  objects,_=self.extract('Nearby.\n\n![](assets/1/figure.png)\n\nCaption.')
  records=[{'resources':objects},{'resources':objects}];messages=[{'role':'system','content':'system'},{'role':'user','content':'evidence'}]
  plain=res.with_images(self.root,messages,{'model':'text','visionModels':['vision']},records)
  self.assertIsInstance(plain[-1]['content'],str);self.assertIn('未提供图像输入',plain[0]['content'])
  visual=res.with_images(self.root,messages,{'model':'vision','visionModels':['vision']},records)
  self.assertEqual(sum(p['type']=='image_url' for p in visual[-1]['content']),1);self.assertIsInstance(messages[-1]['content'],str)
 def test_fingerprint_reuses_references_beyond_parse_cache_capacity(self):
  texts=[f'# {self.root.name} document {i}\n\n![](assets/1/figure.png)\n' for i in range(227)]
  with patch.object(res,'parse',wraps=res.parse) as parse:
   first=[res.fingerprint(self.root,str(i),text) for i,text in enumerate(texts)]
   second=[res.fingerprint(self.root,str(i),text) for i,text in enumerate(texts)]
   self.assertEqual(first,second);self.assertEqual(parse.call_count,227)
   self.asset.write_bytes(PNG+b'changed')
   self.assertNotEqual(first[0],res.fingerprint(self.root,'0',texts[0]))
   self.assertEqual(parse.call_count,227)
   res.fingerprint(self.root,'0',texts[0]+'\nChanged text.')
   self.assertEqual(parse.call_count,228)
 def test_evidence_card_quote_can_point_to_complete_table(self):
  import qa_evidence
  objects,_=self.extract('Before.\n\n| X | Y |\n|---|---|\n| A | 8 |\n\nAfter.')
  record={'text':'Before.','resources':objects}
  card=qa_evidence.validate_card({'score':8,'relation':'direct','summary':'A is 8','quotes':['| A | 8 |']},record,qa.quote_match)
  self.assertEqual(card['quotes'][0]['resourceId'],objects[0]['id'])
  start=card['quotes'][0]['sourceStart'];self.assertEqual(objects[0]['content'][start:start+9],'| A | 8 |')
 def test_remote_or_outside_images_are_not_read_and_code_is_not_extracted(self):
  text='![](../../secret.png)\n\n![](https://example.com/x.png)\n\n```md\n![](assets/1/figure.png)\n```'
  objects,_=self.extract(text);self.assertEqual(len(objects),2);self.assertTrue(all('assetPath' not in o for o in objects))
 def test_html_and_reference_images(self):
  text='<table><tr><td>Value</td></tr></table>\n\n![x][pic]\n\n[pic]: assets/1/figure.png\n'
  objects,_=self.extract(text);self.assertEqual([o['kind'] for o in objects],['table','figure'])
 def test_answer_material_and_review_materials_keep_full_resources(self):
  objects,_=self.extract('Before.\n\n| X | Y |\n|---|---|\n| A | 8 |\n\nAfter.')
  r={'eid':'E1','text':'short','metadata':{'pmid':'12345','title':'Title','sourceKind':'fulltext'},'resources':objects}
  material,compact,omitted=qa.answer_material([r],[],1)
  self.assertFalse(compact);self.assertEqual(omitted,[]);self.assertEqual(material[0]['resources'],objects)
  unit={'nodes':[{'serial':'1'}],'leaves':[{'serial':'1','id':'a','title':'Topic'}]}
  scopes,refs,blocks=review_format.materials(unit,{'a':{'chunks':[r,r]}})
  self.assertEqual(blocks['1'].count('[关联表格 '),1);self.assertIn(objects[0]['content'],blocks['1'])

class ResourceIntegrationTests(unittest.TestCase):
 setUp=fixture.CleaningIntegrationTests.setUp
 tearDown=fixture.CleaningIntegrationTests.tearDown
 job=fixture.CleaningIntegrationTests.job
 def prepare(self):
  clean.rpc(e,'settings.save',{'project':e.PROJECT,'cleaningMode':'references-v1'})
  raw='Small caption.\n\n![](../assets/1/figure.png)\n\nNearby.\n\n| Gene | Value |\n|---|---|\n| A | 1 |\n\nShort tail.\n\n'+REF
  e.atomic(self.base/'markdown/raw/1.md',raw);e.atomic(self.base/'markdown/assets/1/figure.png',PNG)
  meta=json.loads((self.base/'metadata/markdown/1.json').read_text());meta['rawSha256']=hashlib.sha256(raw.encode()).hexdigest();e.write_json(self.base/'metadata/markdown/1.json',meta)
  job,_=self.job('resources');self.assertEqual(job['completed'],1,job)
  chunks.sync(e)
  with chunks.connect(e) as c:
   doc=c.execute('SELECT * FROM current_documents WHERE pmid="1"').fetchone()
   return chunks.records_for(c,doc['version'],json.loads(doc['meta']))
 def test_worker_index_and_historical_image_snapshot(self):
  records=self.prepare();self.assertTrue(any(r['text']=='Small caption.' for r in records));self.assertEqual({o['kind'] for r in records for o in r['resources']},{'figure','table'})
  obj=next(o for r in records for o in r['resources'] if o['kind']=='figure');old_version=records[0]['metadata']['documentVersion']
  self.assertTrue(res.image_rpc(e,obj['id'])['dataUrl'].startswith('data:image/png'))
  e.atomic(self.base/'markdown/assets/1/figure.png',PNG+b'changed');chunks.sync(e)
  with chunks.connect(e) as c:
   new=c.execute('SELECT version FROM current_documents WHERE pmid="1"').fetchone()[0]
   old=chunks.records_for(c,old_version,records[0]['metadata'])
  self.assertNotEqual(new,old_version);self.assertTrue(old);self.assertEqual(base64.b64decode(res.image_rpc(e,obj['id'])['dataUrl'].split(',')[1]),PNG)
 def test_qa_and_review_receive_resources_without_duplicate_embeddings(self):
  records=self.prepare()
  from review_retrieval import Retriever
  with patch('review_retrieval.APIRecall') as api:
   api.return_value.recall.return_value=[(0,.9),(1,.8)]
   found=Retriever(e.ROOT,self.base/'vectors',records,lambda:None,lambda x:None,cfg={'method':'api'},e=e).retrieve('Gene',10,2)
  self.assertTrue(found);self.assertTrue(found[0]['resources']);self.assertNotIn('关联表格',chunks.embedding_text(found[0]))
  item=qa.evidence_input({**found[0],'eid':'E1'});self.assertTrue(item['resources'])
  self.assertEqual(res.unique(found)[0]['documentVersion'],found[0]['metadata']['documentVersion'])
 def test_removed_document_releases_only_unshared_image_snapshots(self):
  records=self.prepare();obj=next(o for r in records for o in r['resources'] if o['kind']=='figure');asset=self.base/obj['assetPath']
  shared={**obj,'id':'shared','pmid':'2','documentVersion':'v2'}
  with chunks.connect(e) as c:c.execute('INSERT INTO resources VALUES(?,?,?,?)',('shared','v2','2',json.dumps(shared)))
  chunks.purge_documents(e,{'1'});self.assertTrue(asset.is_file())
  chunks.purge_documents(e,{'2'});self.assertFalse(asset.exists())

if __name__=='__main__':unittest.main()
