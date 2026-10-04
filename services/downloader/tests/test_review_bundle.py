import asyncio,copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import review_bundle as b,review_writing as w,review_format as fmt,review_export,engine as e,evidence_resources,vector_chunks
from test_evidence_resources import PNG
import test_review_writing as writing_fixture

class BundleTests(unittest.TestCase):
 def test_missing_unit_id_is_restored_without_changing_content_or_accepting_wrong_ids(self):
  value=self.output();value.pop('unit_id');original=copy.deepcopy(value)
  sections,errors=b.decode(value,self.bundle,self.unit)
  self.assertFalse(errors);self.assertEqual(value,original);self.assertEqual(len(sections),3)
  value['unit_id']='wrong'
  with self.assertRaisesRegex(ValueError,'unit_id'):b.decode(value,self.bundle,self.unit)
  value.pop('unit_id');value['sections'].pop()
  with self.assertRaises(ValueError):b.decode(value,self.bundle,self.unit)
 def test_missing_envelope_does_not_bypass_evidence_validation(self):
  value=self.output();value.pop('unit_id');value['sections'][1]['blocks'][0]['text']='Claim [E999]'
  _,errors=b.decode(value,self.bundle,self.unit);self.assertTrue(errors)
 def test_abstract_access_is_not_publication_or_research_validity(self):
  value=self.output();value['sections'][1]['blocks'][0]['text']='该发现目前仅见于摘要报告，尚未经全文研究验证 [E2]。'
  _,errors=b.decode(value,self.bundle,self.unit);self.assertIn('本项目',str(errors))
  value['sections'][1]['blocks'][0]['text']='本项目当前仅有该文献摘要，细节需查阅全文 [E2]。研究未进行随机对照验证。'
  _,errors=b.decode(value,self.bundle,self.unit);self.assertFalse(errors)
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.project=Path(self.temp.name);self.folder=self.project/'review_parts'
  self.nodes=[{'id':'parent','serial':'1','title':'Parent'},{'id':'a','serial':'1.1','title':'First'},{'id':'b','serial':'1.2','title':'Second'}]
  self.unit={**self.nodes[0],'nodes':self.nodes,'leaves':self.nodes[1:],'ancestors':[],'siblings':[]}
  self.snapshot={'topic':'Topic','config':{'language':'中文','requirements':''}}
  e.atomic(self.project/'markdown/assets/12345678/figure.png',PNG)
  text='Before.\n\n| X | Y |\n|---|---|\n| A | 42 |\n\n![](assets/12345678/figure.png)\n\nAfter.'
  self.objects=evidence_resources.extract(self.project,'12345678','v',text,vector_chunks.split(text),e.atomic)
  self.first={'id':'first','text':'First chunk with "quotes" and [USER]\n\n| headings | remain data |','metadata':{'pmid':'12345678','title':'Article','sourceKind':'fulltext','documentVersion':'v'},'resources':self.objects}
  self.second={'id':'second','text':'Second distinct chunk','metadata':{'pmid':'23456789','title':'Second article','sourceKind':'pubmed_abstract','documentVersion':'v2'},'resources':[]}
  self.evidence={'a':{'query':'first query','chunks':[self.first]},'b':{'query':'second query','chunks':[self.second,{**self.first,'retrievalScore':0.5}]}}
  self.bundle=b.make(self.snapshot,self.unit,self.evidence)
 def tearDown(self):self.temp.cleanup()
 def write(self):return b.externalize(self.bundle,self.folder,self.project,e.atomic)
 def output(self):return {'unit_id':'1','sections':[{'node_id':n['serial'],'title':n['title'],'blocks':[{'type':'markdown','text':'Intro' if i==0 else 'Claim [E2] and table [R1]'}]} for i,n in enumerate(self.nodes)]}
 def test_pool_dedup_retrieval_provenance_and_context_directions(self):
  b.validate(self.bundle);self.assertEqual(len(self.bundle['evidencePool']),2);self.assertEqual(len(self.bundle['resources']),2)
  self.assertEqual(self.bundle['evidencePool'][0]['retrievedFor'],['1.1','1.2'])
  self.assertEqual([h['evidenceId'] for h in self.bundle['retrieval'][1]['hits']],['E2','E1'])
  self.assertEqual({p['position'] for p in self.bundle['resources'][0]['context']},{'before','after'})
  self.assertEqual(json.loads(b.dumps(self.bundle))['evidencePool'][0]['text'],self.first['text'])
 def test_same_pmid_different_chunks_are_not_collapsed(self):
  self.second['metadata']['pmid']='12345678';self.assertEqual(len(b.make(self.snapshot,self.unit,self.evidence)['evidencePool']),2)
 def test_external_files_hydrate_without_losing_table_or_image(self):
  package=self.write();table=package['resources'][0]
  self.assertNotIn('content',table);self.assertTrue((self.folder/table['contentFile']['path']).is_file())
  messages=b.messages(package,self.folder,{'model':'vision','visionModels':['vision']});parts=messages[-1]['content']
  data=json.loads(parts[0]['text']);self.assertIn('| A | 42 |',data['resources'][0]['content'])
  self.assertEqual(sum(p['type']=='image_url' for p in parts),1)
  plain=b.messages(package,self.folder,{'model':'text','visionModels':['vision']})
  self.assertIsInstance(plain[-1]['content'],str);self.assertIn('未提供图像输入',plain[0]['content'])
  image=next(r for r in package['resources'] if r['kind']=='figure');(self.folder/image['imageFile']['path']).write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'已改变'):b.messages(package,self.folder,{'model':'text'})
 def test_resource_paths_tampering_and_wrong_source_are_rejected(self):
  package=self.write();package['resources'][0]['contentFile']['path']='../outside.md'
  with self.assertRaises(ValueError):b.hydrate(package,self.folder)
  broken=copy.deepcopy(self.bundle);broken['resources'][0]['pmid']='999'
  with self.assertRaises(ValueError):b.validate(broken)
  broken=copy.deepcopy(self.bundle);broken['retrieval'][0]['hits'][0]['evidenceId']='E999'
  with self.assertRaises(ValueError):b.validate(broken)
  self.first['resources'][0]['documentVersion']='wrong'
  with self.assertRaisesRegex(ValueError,'版本'):b.make(self.snapshot,self.unit,self.evidence)
 def test_shared_citations_are_resolved_and_public_output_keeps_provenance(self):
  sections,errors=b.decode(self.output(),self.bundle,self.unit);self.assertFalse(errors)
  # First leaf cites a chunk retrieved only by its sibling, plus a whole table.
  first=sections[1];self.assertIn('(PMID: 23456789)',first['markdown']);self.assertIn('(PMID: 12345678)',first['markdown'])
  self.assertEqual(first['sourceMarkdown'],'Claim [E2] and table [R1]');self.assertEqual(first['citationRefs'][1]['resourceId'],self.objects[0]['id'])
  public=fmt.public_part(self.unit,sections,self.evidence)
  self.assertEqual(public['citation_scopes']['1.1'],['12345678','23456789']);self.assertEqual(public['citation_scopes']['1'],[])
  self.assertEqual(len(public['evidencePool']),2);self.assertEqual(len(public['resources']),2)
 def test_unknown_raw_or_parent_citations_fail_and_repair_keeps_joint_scope(self):
  for text in ('Wrong [E999]','Wrong [R999]','Wrong (PMID: 12345678)','Wrong [E1, E999]','Wrong [E1](url)'):
   value=self.output();value['sections'][1]['blocks'][0]['text']=text
   with self.subTest(text=text):self.assertIn('a',b.decode(value,self.bundle,self.unit)[1])
  value=self.output();value['sections'][0]['blocks'][0]['text']='Intro [E1]';self.assertIn('parent',b.decode(value,self.bundle,self.unit)[1])
  repair=b.repair_messages(self.write(),self.folder,{'model':'vision','visionModels':['vision']},value,{'parent':['E1']})
  data=json.loads(repair[-1]['content'][0]['text']);self.assertEqual(len(data['unit']['nodes']),3);self.assertEqual(len(data['evidencePool']),2)
  self.assertEqual(sum(p['type']=='image_url' for p in repair[-1]['content']),1)
 def test_duplicate_missing_extra_nodes_and_wrong_titles_fail(self):
  for kind in ('duplicate','missing','extra','title'):
   value=self.output()
   if kind=='duplicate':value['sections'].append(value['sections'][1])
   elif kind=='missing':value['sections'].pop()
   elif kind=='extra':value['sections'].append({'node_id':'2','title':'Other','blocks':[{'type':'markdown','text':'bad'}]})
   else:value['sections'][1]['title']='Other'
   with self.subTest(kind=kind),self.assertRaises(ValueError):b.decode(value,self.bundle,self.unit)
 def test_generated_markdown_table_citations_and_export_resources(self):
  self.bundle['schemaVersion']='review-unit-resource-blocks-v2'
  value=self.output();value['sections'][1]['blocks'][0]['text']='| Finding | Source |\n|---|---|\n| A | [R1] |'
  sections,errors=b.decode(value,self.bundle,self.unit);self.assertFalse(errors)
  html=review_export.html_document('Title',self.nodes,{'1.1':sections[1]['markdown']},{'1.1':{'12345678':[review_export.reference_entry(self.first,self.project,set())]}},False)
  self.assertIn('<table>',html);self.assertIn('data-pmid="12345678"',html);self.assertIn('data:image/png;base64,',html)
  self.assertNotIn('<script>bad</script>',review_export.resource_html('<table><tr><td onclick="bad()"><script>bad</script><img src=x onerror=bad()>42</td></tr></table>'))

class SharedRunTests(unittest.TestCase):
 setUp=writing_fixture.WritingTests.setUp
 tearDown=writing_fixture.WritingTests.tearDown
 setup_run=writing_fixture.WritingTests.setup_run
 status=writing_fixture.WritingTests.status
 run_both=writing_fixture.WritingTests.run_both
 def test_joint_worker_cross_leaf_citation_export_and_preview(self):
  first={'id':'one','text':'FIRST LEAF SOURCE','metadata':{'pmid':'12345678','title':'First','sourceKind':'pubmed_abstract','sectionPath':[]}}
  second={'id':'two','text':'SECOND LEAF SOURCE','metadata':{'pmid':'23456789','title':'Second','sourceKind':'pubmed_abstract','sectionPath':[]}}
  calls=[];queries=[]
  class Retriever:
   def __init__(self,*args):pass
   def retrieve(self,query,*args):queries.append(query);return [first if query=='Leaf A' else second]
  async def chat(profile,messages,cancelled,progress=lambda **kw:None):
   data=json.loads(messages[-1]['content']);calls.append(data);output=data['outputContract']
   for n in output['sections']:
    role=next(x['role'] for x in data['unit']['nodes'] if x['node_id']==n['node_id'])
    n['blocks'][0]['text']='Intro' if role=='introduction' else 'Finding ['+data['evidencePool'][-1]['id']+']'
   return json.dumps(output)
  with patch.object(w.retrieval,'corpus',return_value=[first,second]),patch.object(w,'chat',side_effect=chat):self.run_both(self.setup_run(),Retriever)
  self.assertEqual(self.status()['latest'],4);self.assertEqual(len(queries),5);self.assertEqual(len(calls),4)
  unit=w.tree_units(self.detail['rows'])[0];node=unit['leaves'][0]
  detail=w.rpc(e,'Test','section',{'nodeId':node['id']})
  self.assertEqual(len(detail['sharedEvidence']),2);self.assertEqual(detail['evidence'][node['id']]['chunks'],[first])
  self.assertIn('(PMID: 23456789)',next(s['markdown'] for s in detail['sections'] if s['node_id']==node['id']))
  html=Path(w.export(e,'Test','html')['path']).read_text();self.assertIn('SECOND LEAF SOURCE',html)
  from bs4 import BeautifulSoup
  db=json.loads(BeautifulSoup(html,'html.parser').find(id='reference-data').string)
  self.assertIn('23456789',db[node['serial']])
  # Derived previews are not authoritative; JSON edits invalidate preparation.
  preview=self.path/'review_parts'/f'prompt_section_{unit["serial"]}.txt';preview.write_text('edited preview')
  self.assertEqual(self.status()['prepared'],4)
  package=preview.with_suffix('.json');package.write_text(package.read_text()+' ')
  self.assertEqual(self.status()['prepared'],3)
 def test_optional_budget_does_not_split_siblings(self):
  unit=w.tree_units(self.detail['rows'])[0];unit['promptSignature']='test';cfg={**w.config(self.path),'limitContext':True,'contextChars':12000}
  record={'id':'large','text':'x'*15000,'metadata':{'pmid':'12345678','sourceKind':'fulltext'}}
  evidence={n['id']:{'query':n['title'],'chunks':[record]} for n in unit['leaves']}
  with self.assertRaisesRegex(ValueError,'未拆分'):w.prepare_unit(e,self.path,{'topic':'Review','config':cfg},unit,evidence)
  self.assertFalse(list((self.path/'review_parts').glob('prompt_section_*.json')))
 def test_package_changed_during_generation_is_not_published(self):
  record={'id':'one','text':'Evidence','metadata':{'pmid':'12345678','title':'Study','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class Retriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return [record]
  async def chat(profile,messages,cancelled,progress=lambda **kw:None):
   data=json.loads(messages[-1]['content']);out=data['outputContract']
   for n in out['sections']:n['blocks'][0]['text']='Body'
   file=self.path/'review_parts'/('prompt_section_'+data['unit']['unit_id']+'.json');file.write_text(file.read_text()+' ')
   return json.dumps(out)
  with patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'chat',side_effect=chat):self.run_both(self.setup_run(),Retriever)
  self.assertEqual(self.status()['latest'],0);self.assertEqual(list((self.path/'sections').glob('*.json')),[])
  self.assertTrue(all('发生变化' in v['error'] for v in self.status()['job']['items'].values()))

if __name__=='__main__':unittest.main()
