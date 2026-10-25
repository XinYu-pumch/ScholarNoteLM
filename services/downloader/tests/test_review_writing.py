import asyncio,json,os,sys,tempfile,unittest,uuid,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,review_service as r,review_writing as w,storage

PROFILE={'id':'test','model':'fixture','endpoint':'http://127.0.0.1/chat/completions','sendTemperature':False}
CSV='Serial,Title\n1,Parent\n1.1,Branch\n1.1.1,Leaf A\n1.1.2,Leaf B\n1.2,Leaf C\n1.3,Deep branch\n1.3.1,Deeper branch\n1.3.1.1,Leaf D\n2,Conclusion\n'
class WritingTests(unittest.TestCase):
 def setUp(self):
  self.old=(e.ROOT,e.PROJECT);self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test'
  self.base=storage.project_dir(e.ROOT,e.PROJECT);self.path=self.base/'review/Test'
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet/>')
  r.rpc(e,'create',{'name':'Test','topic':'Review'})
  self.detail=r.rpc(e,'import',{'name':'Test','revision':0,'csv':CSV})
  self.profile=patch.object(r,'profile',return_value=PROFILE);self.profile.start()
 def tearDown(self):self.profile.stop();e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def status(self):return r.rpc(e,'writing.status',{'name':'Test'})
 def test_selected_model_is_used_without_invalidating_prepared_materials(self):
  original=w.config(self.path);selected=w.config(self.path,{'profileId':'other-provider','model':'selected-model'})
  unit=w.tree_units(self.detail['rows'])[0]
  self.assertEqual(w.unit_signature(unit,original,'topic','source','','retrieval'),w.unit_signature(unit,selected,'topic','source','','retrieval'))
  self.assertNotEqual(w.unit_signature(unit,original,'topic','source','old-model','retrieval'),w.unit_signature(unit,selected,'topic','source','selected-model','retrieval'))
  e.write_json(self.path/'writing-settings.json',selected)
  with patch.object(r,'profile',return_value={**PROFILE,'model':'selected-model'}) as resolve:
   result=self.status();resolve.assert_called_with(e,'other-provider','selected-model')
  self.assertEqual(result['model'],'selected-model')
 def test_mixed_depth_unit_coverage(self):
  units=w.tree_units(self.detail['rows']);self.assertEqual([u['serial'] for u in units],['1.1','1.2','1.3.1','2'])
  leaves=[n['serial'] for u in units for n in u['leaves']];self.assertEqual(leaves,['1.1.1','1.1.2','1.2','1.3.1.1','2'])
 def test_stable_ids_survive_title_change_and_renumber(self):
  rows=self.detail['rows'];old=rows[0]['id'];rows[0]['title']='Changed title'
  d=r.rpc(e,'save',{'name':'Test','revision':1,'topic':'Review','rows':rows});self.assertEqual(d['rows'][0]['id'],old)
  roots=[{'serial':'1','title':'New chapter'},*[{**n,'serial':str(int(n['serial'].split('.')[0])+1)+('.'+n['serial'].split('.',1)[1] if '.' in n['serial'] else '')} for n in d['rows']]]
  d=r.rpc(e,'save',{'name':'Test','revision':2,'topic':'Review','rows':roots});self.assertEqual(d['rows'][1]['id'],old)
 def test_vision_changes_are_scoped_to_selected_model(self):
  for provider in ('openai','opencode_go'):
   p={**PROFILE,'provider':provider,'visionModels':['fixture','other'],'reasoningByModel':{'fixture':'high'}}
   original=w.profile_signature(p)
   for vision in (['fixture'],['other','fixture','third'],['fixture','fixture']):
    self.assertEqual(w.profile_signature({**p,'visionModels':vision}),original)
   for change in ({'visionModels':['other']},{'model':'other'},{'temperature':.4},{'endpoint':'https://different.example/v1'}):
    self.assertNotIn(original,w.compatible_profile_signatures({**p,**change}))
   if provider=='opencode_go':
    self.assertNotIn(original,w.compatible_profile_signatures({**p,'reasoningByModel':{'fixture':'low'}}))
   plain={**p,'visionModels':[]}
   self.assertEqual(w.profile_signature(plain),w.profile_signature({**plain,'visionModels':['unrelated']}))

 def test_legacy_single_model_vision_restores_status_without_rewriting(self):
  for provider in ('openai','opencode_go'):
   old={**PROFILE,'provider':provider,'visionModels':['fixture'],'reasoningByModel':{'fixture':'high'}}
   with patch.dict(PROFILE,old):self.seed()
   # This singleton hash is exactly the pre-fix representation, not a new cache.
   cfg=w.config(self.path);source=w.source_signature(e);models=w.retrieval.signature(e.ROOT)
   for u in w.tree_units(self.detail['rows']):
    f=self.path/'sections'/f'{u['id']}.json';saved=r.read(f)
    saved['signature']=w.unit_signature(u,cfg,'Review',source,w.legacy_profile_signature(old),models,legacy=True)
    e.write_json(f,saved)
   files=list((self.path/'sections').glob('*.json'));before={f:f.read_bytes() for f in files}
   with patch.object(r,'profile',return_value={**old,'visionModels':['fixture','other']}):
    result=self.status();self.assertEqual(result['latest'],4)
    self.assertEqual(result['stages']['writing'],{'state':'complete','completed':7,'total':7})
   self.assertEqual(before,{f:f.read_bytes() for f in files})
   with patch.object(r,'profile',return_value={**old,'visionModels':['other']}):self.assertEqual(self.status()['latest'],0)

 def test_legacy_full_vision_list_survives_upgrade_and_retry_skips_it(self):
  p={**PROFILE,'visionModels':['fixture','other']}
  with patch.dict(PROFILE,p):
   self.seed();cfg=w.config(self.path);source=w.source_signature(e);models=w.retrieval.signature(e.ROOT)
   units=w.tree_units(self.detail['rows'])
   for u in units:
    u['promptSignature']=w.unit_signature(u,cfg,'Review',source,'',models)
    f=self.path/'sections'/f'{u["id"]}.json';saved=r.read(f)
    pre=w.prepare_unit(e,self.path,{'config':cfg,'topic':'Review'},u,saved['evidence'])
    saved['signature']=w.unit_signature(u,cfg,'Review',source,w.legacy_profile_signature(p),models,pre['hash']);e.write_json(f,saved)
   with patch.object(r,'profile',return_value={**p,'visionModels':['third','other','fixture']}):self.assertEqual(self.status()['latest'],4)
   with patch.object(w.subprocess,'Popen') as proc:
    result=w.rpc(e,'Test','retry',{});proc.assert_not_called()
   self.assertEqual(result['latest'],4)
   with patch.object(r,'profile',return_value={**p,'temperature':.4}):self.assertEqual(self.status()['latest'],0)
   e.write_json(self.path/'writing-settings.json',{'topK':8});self.assertEqual(self.status()['latest'],0)

 def test_legacy_empty_vision_hash_is_accepted_without_weakening_validation(self):
  p={**PROFILE,'visionModels':[]};old=w.legacy_profile_signature(p)
  self.assertIn(old,w.compatible_profile_signatures({**p,'visionModels':['other']}))
  self.assertNotIn(old,w.compatible_profile_signatures({**p,'visionModels':['fixture']}))
  # Unknown historical lists cannot be recovered from a hash: fail closed.
  unknown=w.legacy_profile_signature({**p,'visionModels':['removed','fixture']})
  self.assertNotIn(unknown,w.compatible_profile_signatures({**p,'visionModels':['fixture']}))

 def test_legacy_budget_and_duplicate_profile_restore_without_rewriting(self):
  self.seed();cfg=w.config(self.path,{'profileId':'original','contextChars':12000,'limitContext':True})
  ctx=w.manuscripts.new_round(e,'Test',self.detail['rows'],'Review',cfg)
  e.write_json(self.path/'writing-round.json',ctx)
  source=w.source_signature(e);models=w.retrieval.signature(e.ROOT)
  token=uuid.uuid4().hex;e.write_json(self.path/'logs'/token/'input.json',{'config':cfg})
  for u in w.tree_units(self.detail['rows']):
   u['promptSignature']=w.unit_signature(u,cfg,'Review',source,'',models,legacy=True)
   f=self.path/'sections'/f'{u['id']}.json';saved=r.read(f)
   pre=w.prepare_unit(e,self.path,{'config':cfg,'topic':'Review'},u,saved['evidence'])
   saved.update(run=token,signature=w.unit_signature(u,cfg,'Review',source,w.legacy_profile_signature({**PROFILE,'id':'original'}),models,pre['hash'],legacy=True));e.write_json(f,saved)
  before={f:f.read_bytes() for f in self.path.rglob('*.json')}
  e.write_json(self.path/'writing-settings.json',{**cfg,'profileId':'copy','contextChars':500000,'limitContext':False})
  with patch.object(r,'profile',return_value={**PROFILE,'id':'copy'}):
   state=self.status();self.assertEqual(state['latest'],4);self.assertEqual(state['prepared'],4)
   with patch.object(w.subprocess,'Popen') as spawn:w.rpc(e,'Test','retry',{});spawn.assert_not_called()
  for f,content in before.items():
   if f.name!='writing-settings.json':self.assertEqual(f.read_bytes(),content)
  e.write_json(self.path/'writing-settings.json',{**cfg,'requirements':'New actual instructions'})
  self.assertEqual(self.status()['latest'],0);self.assertEqual(self.status()['prepared'],0)

 def test_new_outputs_ignore_transport_duplicate_id_and_budget(self):
  self.seed()
  e.write_json(self.path/'writing-settings.json',{'limitContext':True,'contextChars':12000})
  with patch.object(r,'profile',return_value={**PROFILE,'id':'copy','timeout':900,'apiKey':'synthetic'}):self.assertEqual(self.status()['latest'],4)

 def test_scope_and_structure_validation(self):
  u=w.tree_units(self.detail['rows'])[0];ids=[n['id'] for n in u['nodes']];ev={ids[1]:{'chunks':[{'metadata':{'pmid':'1'}}]},ids[2]:{'chunks':[{'metadata':{'pmid':'2'}}]}}
  good={'sections':[{'node_id':i,'markdown':'Evidence'+(' (PMID: 1)' if i==ids[1] else '')} for i in ids]}
  self.assertEqual(w.validate(good,u,ev)[1],{})
  good['sections'][2]['markdown']='Wrong neighbour (PMID: 1)';self.assertEqual(w.validate(good,u,ev)[1],{ids[2]:['1']})
  for invalid in [good['sections'][:-1],good['sections']+[good['sections'][0]],[{'node_id':'unknown','markdown':'x'}]]:
   with self.assertRaises(ValueError):w.validate({'sections':invalid},u,ev)
 def seed(self):
  cfg=w.config(self.path);src=w.source_signature(e);sig=w.profile_signature(PROFILE);models=w.retrieval.signature(e.ROOT)
  for u in reversed(w.tree_units(self.detail['rows'])):
   evidence={n['id']:{'query':n['title'],'chunks':[{'id':'chunk','text':'<script>unsafe</script> evidence','metadata':{'pmid':'123','title':'Evidence title','sourceKind':'pubmed_abstract','sectionPath':[]}}]} for n in u['leaves']}
   sections=[{'node_id':n['id'],'markdown':'Body for '+n['serial']+(' (PMID: 123)' if n['id'] in evidence else '')} for n in u['nodes']]
   e.write_json(self.path/'sections'/f'{u["id"]}.json',{'signature':w.unit_signature(u,cfg,'Review',src,sig,models),'sections':sections,'evidence':evidence})
   e.write_json(self.path/'review_parts'/f'section_{u["serial"]}.json',w.review_format.public_part(u,sections,evidence))
 def test_assembly_order_all_headings_and_latest(self):
  self.seed();md,state,*_=w.assemble(e,'Test');self.assertEqual(state['latest'],state['total']);self.assertEqual(state['total'],4)
  positions=[md.index(n['serial']+' '+n['title']) for n in self.detail['rows']];self.assertEqual(positions,sorted(positions))
  self.assertEqual(md.count('Body for 1.1.1'),1);self.assertIn('1.3.1.1 Leaf D',md)
 def test_source_change_marks_stale_and_concurrency_does_not(self):
  self.seed();self.assertEqual(self.status()['latest'],4)
  e.write_json(self.path/'writing-settings.json',{'concurrency':7});self.assertEqual(self.status()['latest'],4)
  e.write_json(self.path/'writing-settings.json',{'topK':8});self.assertEqual(self.status()['latest'],0)
  e.write_json(self.path/'writing-settings.json',{});e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>New</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>');self.assertEqual(self.status()['latest'],0)
 def test_exports_preserve_tree_and_escape_evidence(self):
  self.seed()
  exports={}
  for fmt in ('md','html','docx'):
   result=w.export(e,'Test',fmt);self.assertFalse(result['partial']);self.assertTrue(Path(result['path']).exists());exports[fmt]=Path(result['path'])
  html=exports['html'].read_text();self.assertNotIn('<script>unsafe</script>',html);self.assertIn('unsafe',html);self.assertIn(r'\u0026lt;script',html)
  import xml.etree.ElementTree as ET
  with zipfile.ZipFile(exports['docx']) as z:
   for f in z.namelist():
    if f.endswith(('.xml','.rels')):ET.fromstring(z.read(f))
   self.assertIn('1.3.1.1 Leaf D',z.read('word/document.xml').decode())
 def test_active_job_prevents_mutations(self):
  e.write_json(self.path/'writing-job.json',{'state':'running','pid':os.getpid()})
  for op in ('save','restore','delete','start','writing.settings','writing.start'):
   with self.subTest(op=op),self.assertRaisesRegex(ValueError,'撰写'):r.rpc(e,op,{'name':'Test','revision':1,'confirm':'Test'})
  self.assertEqual(r.rpc(e,'writing.cancel',{'name':'Test'})['job']['state'],'stopping')
 def test_orphaned_start_is_recoverable(self):
  import time
  e.write_json(self.path/'writing-job.json',{'state':'queued','pid':0,'created':time.time()-40})
  self.assertEqual(self.status()['job']['state'],'failed')
 def test_numeric_parameter_validation(self):
  for cfg in ({'concurrency':0},{'topK':0},{'concurrency':True},{'topK':1.2}):
   with self.assertRaises(ValueError):w.config(self.path,cfg)
 def setup_run(self,mode="prepare"):
  token=uuid.uuid4().hex;cfg=w.config(self.path);src=w.source_signature(e);models=w.retrieval.signature(e.ROOT)
  units=w.tree_units(self.detail['rows'])
  for u in units:
   u['promptSignature']=w.unit_signature(u,cfg,'Review',src,'',models)
   pre=w.prepared(self.path,u,u['promptSignature'])
   u['signature']=w.unit_signature(u,cfg,'Review',src,w.profile_signature(PROFILE),models,pre['hash'] if pre else '')
  e.write_json(self.path/'logs'/token/'input.json',{'mode':mode,'token':token,'config':cfg,'topic':'Review','profileId':'test','profileSignature':w.profile_signature(PROFILE),'sourceSignature':src,'modelsSignature':models,'tasks':units,'rows':self.detail['rows']})
  e.write_json(self.path/'writing-job.json',{'token':token,'state':'queued','pid':os.getpid(),'items':{u['id']:{'state':'pending'} for u in units}})
  return token
 def run_both(self,token,factory):
  asyncio.run(w.run(e,'Test',token,factory))
  self.assertEqual(self.status()['prepared'],4,self.status()['job'])
  self.assertEqual(len(list((self.path/'review_parts').glob('prompt_section_*.txt'))),4)
  write=self.setup_run('write');asyncio.run(w.run(e,'Test',write,factory));return write
 def test_write_and_scoped_repair_receive_complete_resources(self):
  from test_evidence_resources import PNG
  import evidence_resources as resources,vector_chunks as chunks
  e.atomic(self.base/'markdown/assets/123/figure.png',PNG)
  source='Context.\n\n![](assets/123/figure.png)\n\n| Gene | Value |\n|---|---|\n| A | 42 |\n\nCaption.'
  objects=resources.extract(self.base,'123','v',source,chunks.split(source),e.atomic)
  record={'id':'c1','text':'Context.','metadata':{'pmid':'123','title':'Article','sourceKind':'fulltext','documentVersion':'v','sectionPath':[]},'resources':objects}
  calls=[]
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return [record]
  async def fake_chat(profile,messages,cancelled,progress=lambda **kw:None):
   parts=messages[-1]['content'];self.assertIsInstance(parts,list);calls.append(parts)
   self.assertEqual(sum(p['type']=='image_url' for p in parts),1)
   content=parts[0]['text'];self.assertIn('| A | 42 |',content)
   data=json.loads(content);payload=data['outputContract'];leaves={n['node_id'] for n in data['unit']['nodes'] if n['role']=='leaf'}
   for node in payload['sections']:node['blocks'][0]['text']=('Evidence [R1]' if 'repair' in data else 'Evidence [E999]') if node['node_id'] in leaves else 'Introduction'
   return json.dumps(payload)
  with patch.dict(PROFILE,{'visionModels':['fixture']}),patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'chat',side_effect=fake_chat):
   self.run_both(self.setup_run(),FakeRetriever)
   state=self.status();self.assertEqual(state['job']['state'],'done',state['job']);self.assertEqual(state['latest'],4)
  self.assertGreater(len(calls),4)
  logs=list((self.path/'logs').glob('*/*.repair.prompt.json.gz'));self.assertTrue(logs)
  self.assertIn('data:image/png;base64,',w.compact_io.read_text(logs[0]))
 def test_complete_pipeline_repair_and_resume_cache(self):
  token=self.setup_run();calls=[];retrieved=[]
  record={'id':'c1','text':'Evidence supporting the topic.','metadata':{'pmid':'123','title':'Article','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,q,k,n):retrieved.append(q);return [record]
  async def fake_chat(p,messages,cancelled,progress=lambda **kw:None):
   calls.append(messages);progress(received=30,reasoningCharacters=4)
   data=json.loads(messages[-1]['content']);payload=data['outputContract'];leaves={n['node_id'] for n in data['unit']['nodes'] if n['role']=='leaf'}
   for n in payload['sections']:n['blocks'][0]['text']=('Evidence [E1]' if 'repair' in data else 'Evidence [E999]') if n['node_id'] in leaves else 'Introduction'
   return json.dumps(payload)
  with patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'chat',side_effect=fake_chat):self.run_both(token,FakeRetriever)
  state=self.status();self.assertEqual(state['job']['state'],'done',state['job']);self.assertEqual(state['latest'],4);self.assertEqual(len(retrieved),5)
  self.assertTrue(list((self.path/'logs').glob('*/*.repair.response.txt.gz')))
  token=self.setup_run();retrieved.clear()
  with patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'chat',side_effect=fake_chat):self.run_both(token,FakeRetriever)
  self.assertEqual(retrieved,[]);self.assertEqual(self.status()['latest'],4)
 def test_worker_vision_guard_accepts_unrelated_changes_but_rejects_selected_toggle(self):
  record={'id':'c1','text':'Evidence','metadata':{'pmid':'123','title':'Article','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return [record]
  async def fake_chat(profile,messages,cancelled,progress=lambda **kw:None):
   output=json.loads(messages[-1]['content'])['outputContract']
   for node in output['sections']:node['blocks'][0]['text']='Body'
   return json.dumps(output)
  with patch.object(w.retrieval,'corpus',return_value=[record]):asyncio.run(w.run(e,'Test',self.setup_run(),FakeRetriever))
  with patch.dict(PROFILE,{'visionModels':['fixture','other']}):token=self.setup_run('write')
  with patch.dict(PROFILE,{'visionModels':['third','fixture']}),patch.object(w,'chat',side_effect=fake_chat) as chat:
   asyncio.run(w.run(e,'Test',token,FakeRetriever));self.assertEqual(chat.call_count,4)
   self.assertEqual(self.status()['latest'],4)
  # A queued pre-fix task with a full-list hash still works if unchanged.
  with patch.dict(PROFILE,{'visionModels':['fixture','other']}):
   token=self.setup_run('write');f=self.path/'logs'/token/'input.json';snap=r.read(f)
   snap['profileSignature']=w.legacy_profile_signature(PROFILE);e.write_json(f,snap)
   with patch.object(w,'chat',side_effect=fake_chat) as chat:
    asyncio.run(w.run(e,'Test',token,FakeRetriever));self.assertEqual(chat.call_count,4)
   token=self.setup_run('write')
  with patch.dict(PROFILE,{'visionModels':['other']}),patch.object(w,'chat') as chat:
   asyncio.run(w.run(e,'Test',token,FakeRetriever));chat.assert_not_called()
   self.assertEqual(self.status()['job']['state'],'failed')
   self.assertIn('模型配置已变化',self.status()['job']['error'])
 def test_writing_concurrency_is_bounded(self):
  token=self.setup_run();live=0;peak=0
  record={'id':'c1','text':'Evidence','metadata':{'pmid':'123','title':'Article','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return [record]
  async def fake_chat(profile,messages,cancelled,progress=lambda **kw:None):
   nonlocal live,peak
   live+=1;peak=max(peak,live)
   try:
    await asyncio.sleep(.08)
    p=json.loads(messages[-1]['content'])['outputContract']
    return json.dumps({**p,'sections':[{**n,'blocks':[{'type':'markdown','text':'Evidence'}]} for n in p['sections']]})
   finally:live-=1
  with patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'chat',side_effect=fake_chat):self.run_both(token,FakeRetriever)
  self.assertEqual(peak,3);self.assertEqual(self.status()['latest'],4)
 def test_network_checks_never_rescan_sources(self):
  token=self.setup_run();record={'id':'c','text':'Evidence','metadata':{'pmid':'123','title':'Article','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class FakeRetriever:
   def __init__(self,root,cache,records,check,progress):self.check=check
   def retrieve(self,*args):
    for _ in range(100):self.check()
    return [record]
  with patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'source_signature',wraps=w.source_signature) as signature:
   asyncio.run(w.run(e,'Test',token,FakeRetriever))
   self.assertEqual(signature.call_count,1)
  self.assertEqual(r.read(self.path/'writing-job.json')['state'],'done')
 def test_material_change_during_retrieval_does_not_publish(self):
  token=self.setup_run();base=self.base
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):
    e.atomic(base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>9</PMID><Article><ArticleTitle>Changed</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
    return []
  with patch.object(w.retrieval,'corpus',return_value=[]):asyncio.run(w.run(e,'Test',token,FakeRetriever))
  self.assertEqual(r.read(self.path/'writing-job.json')['state'],'failed')
  self.assertEqual(list((self.path/'review_parts').glob('prompt_section_*.json')),[])
  self.assertEqual(list((self.path/'retrieval').glob('*.json')),[])
 def test_source_change_during_generation_does_not_publish(self):
  token=self.setup_run();record={'id':'c1','text':'Evidence','metadata':{'pmid':'123','title':'Article','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return [record]
  async def fake_chat(profile,messages,cancelled,progress=lambda **kw:None):
   e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Changed</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
   p=json.loads(messages[-1]['content'])['outputContract'];return json.dumps({**p,'sections':[{**n,'blocks':[{'type':'markdown','text':'Old evidence'}]} for n in p['sections']]})
  with patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'chat',side_effect=fake_chat):self.run_both(token,FakeRetriever)
  self.assertEqual(self.status()['latest'],0);self.assertEqual(list((self.path/'sections').glob('*.json')),[])
 def test_missing_material_before_request_does_not_send(self):
  token=self.setup_run();base=self.base
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return []
  with patch.object(w.retrieval,'corpus',return_value=[]):asyncio.run(w.run(e,'Test',token,FakeRetriever))
  token=self.setup_run('write');original=w.review_bundle.messages
  def changed(*args,**kwargs):
   messages=original(*args,**kwargs)
   e.atomic(base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>9</PMID><Article><ArticleTitle>Changed</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
   return messages
  with patch.object(w.review_bundle,'messages',side_effect=changed),patch.object(w,'chat') as chat:
   asyncio.run(w.run(e,'Test',token,FakeRetriever));chat.assert_not_called()
  self.assertEqual(r.read(self.path/'writing-job.json')['state'],'partial')
 def test_cancel_during_network_polling_stops_preparation(self):
  token=self.setup_run();path=self.path
  class FakeRetriever:
   def __init__(self,root,cache,records,check,progress):self.check=check
   def retrieve(self,*args):
    self.check();job=r.read(path/'writing-job.json');job['state']='stopping';e.write_json(path/'writing-job.json',job)
    self.check()
    raise AssertionError('Cancellation must interrupt polling')
  with patch.object(w.retrieval,'corpus',return_value=[]):asyncio.run(w.run(e,'Test',token,FakeRetriever))
  self.assertEqual(r.read(path/'writing-job.json')['state'],'cancelled')
  self.assertEqual(list((path/'review_parts').glob('prompt_section_*.json')),[])
 def test_prompt_preparation_without_llm_and_stale_file_detection(self):
  record={'id':'c','text':'Evidence','metadata':{'pmid':'123','title':'Article','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,q,k,n):return [record]
  token=self.setup_run()
  with patch.object(w.retrieval,'corpus',return_value=[record]),patch.object(w,'chat',side_effect=AssertionError('must not call writing LLM')),patch.object(r,'profile',side_effect=ValueError('not configured')):
   asyncio.run(w.run(e,'Test',token,FakeRetriever))
  self.assertEqual(self.status()['prepared'],4)
  self.assertEqual(list((self.path/'sections').glob('*.json')),[])
  first=next((self.path/'review_parts').glob('prompt_section_*.json'));first.write_text(first.read_text()+'changed')
  self.assertEqual(self.status()['prepared'],3)
  with self.assertRaisesRegex(ValueError,'提示词'):r.rpc(e,'writing.start',{'name':'Test'})
 def test_unused_recall_limit_and_rate_do_not_invalidate(self):
  self.seed();self.assertEqual(self.status()['latest'],4)
  e.write_json(e.ROOT/'config/retrieval.json',{'method':'api','reranker':'none','candidateK':2,'rpm':10,'tpm':90000})
  self.assertEqual(self.status()['latest'],4)
  e.write_json(e.ROOT/'config/retrieval.json',{'method':'api','reranker':'qwen3','candidateK':2})
  self.assertEqual(self.status()['latest'],4)  # Removed settings have no effect.
 def test_cancel_retains_completed_body(self):
  self.seed();token=self.setup_run()
  j=r.read(self.path/'writing-job.json');j['state']='stopping';e.write_json(self.path/'writing-job.json',j)
  asyncio.run(w.run(e,'Test',token));self.assertEqual(self.status()['job']['state'],'cancelled');self.assertEqual(len(list((self.path/'sections').glob('*.json'))),4)
 def test_cancel_signal_survives_progress_overwrite(self):
  record={'id':'c1','text':'Evidence','metadata':{'pmid':'123','title':'Article','sourceKind':'pubmed_abstract','sectionPath':[]}}
  class FakeRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return [record]
  with patch.object(w.retrieval,'corpus',return_value=[record]):
   asyncio.run(w.run(e,'Test',self.setup_run(),FakeRetriever))
  self.assertEqual(self.status()['prepared'],4)
  self.seed();token=self.setup_run('write');job_path=self.path/'writing-job.json'
  before={p:p.read_bytes() for p in (self.path/'sections').glob('*.json')};write=e.write_json;injected=[]
  def racing_write(path,value):
   if path==job_path and value.get('state')=='running' and any(v.get('reasoningCharacters')==12 for v in value.get('items',{}).values()) and not injected:
    injected.append(True)
    self.assertEqual(r.rpc(e,'writing.cancel',{'name':'Test'})['job']['state'],'stopping')
   write(path,value)
  async def fake_chat(profile,messages,cancelled,progress=lambda **kw:None):
   progress(received=0,reasoningCharacters=12)
   cancelled()
   raise AssertionError('Cancelled writing must not continue')
  with patch.object(e,'write_json',side_effect=racing_write),patch.object(w,'chat',side_effect=fake_chat):
   asyncio.run(w.run(e,'Test',token))
  self.assertTrue(injected);self.assertEqual(self.status()['job']['state'],'cancelled')
  self.assertEqual(before,{p:p.read_bytes() for p in before})
  next_token=self.setup_run('write')
  self.assertFalse(r.cancel_requested(self.path,'writing',next_token))
  self.assertEqual(w.job(e,'Test')['state'],'queued')
 def test_deleted_public_section_disappears_from_status_preview_and_detail(self):
  self.seed();u=w.tree_units(self.detail['rows'])[0];before=self.status()['fileRevision']
  (self.path/'review_parts'/f'section_{u["serial"]}.json').unlink()
  status=self.status();self.assertEqual(status['latest'],3);self.assertNotEqual(status['fileRevision'],before)
  self.assertFalse(next(i for i in status['units'] if i['id']==u['id'])['hasContent'])
  self.assertNotIn('Body for 1.1.1',w.assemble(e,'Test')[0])
  self.assertEqual(w.rpc(e,'Test','section',{'nodeId':u['leaves'][0]['id']}).get('sections',[]),[])
  self.assertTrue((self.path/'sections'/f'{u["id"]}.json').exists())
 def test_retired_budget_is_ignored_without_invalidating_existing_signatures(self):
  cfg=w.config(self.path);self.assertFalse(cfg['limitContext'])
  u=w.tree_units(self.detail['rows'])[-1];snap={'config':cfg,'topic':'Review'};u['promptSignature']='test'
  messages=[{'role':'system','content':'system'},{'role':'user','content':'x'*510000}]
  with patch.object(w.review_bundle,'messages',return_value=messages):
   self.assertIsNotNone(w.prepare_unit(e,self.path,snap,u,{}))
   legacy=w.config(self.path,{'limitContext':True,'contextChars':1})
   self.assertIsNotNone(w.prepare_unit(e,self.path,{**snap,'config':legacy},u,{}))
  old={k:v for k,v in cfg.items() if k!='limitContext'}
  self.assertEqual(w.unit_signature(u,cfg,'Review','s','p','m'),w.unit_signature(u,old,'Review','s','p','m'))
 def test_progress_distinguishes_failed_pending_and_running(self):
  states=['done']*24+['failed']*20+['writing','validating','pending','cancelled']
  result=w.progress_counts({'items':{str(i):{'state':s} for i,s in enumerate(states)}})
  self.assertEqual(result,{'total':48,'completed':24,'failed':20,'running':2,'pending':1,'cancelled':1,'settled':45})
 def test_retry_includes_pending_and_retains_successful_units(self):
  self.seed();units=w.tree_units(self.detail['rows']);failed=units[0];pending=units[1]
  for u in (failed,pending):(self.path/'review_parts'/f'section_{u["serial"]}.json').unlink()
  e.write_json(self.path/'writing-job.json',{'state':'partial','mode':'write','items':{failed['id']:{'state':'failed','error':'JSON invalid'},pending['id']:{'state':'pending'}}})
  cfg=w.config(self.path);source=w.source_signature(e);models=w.retrieval.signature(e.ROOT)
  for u in units:
   u['promptSignature']=w.unit_signature(u,cfg,'Review',source,'',models)
   pre=w.prepare_unit(e,self.path,{'config':cfg,'topic':'Review'},u,r.read(self.path/'sections'/f'{u["id"]}.json')['evidence'])
   saved=r.read(self.path/'sections'/f'{u["id"]}.json');saved['signature']=w.unit_signature(u,cfg,'Review',source,w.profile_signature(PROFILE),models,pre['hash']);e.write_json(self.path/'sections'/f'{u["id"]}.json',saved)
  with patch.object(w.subprocess,'Popen') as proc:
   proc.return_value.pid=os.getpid();result=w.rpc(e,'Test','retry',{})
  j=r.read(self.path/'writing-job.json');self.assertEqual(list(j['items']),[failed['id'],pending['id']])
  self.assertEqual(j['total'],2)
  self.assertEqual(result['stages']['writing'],{'state':'partial','completed':3,'total':7})
 def prepare_seeded_units(self):
  self.seed();cfg=w.config(self.path);source=w.source_signature(e);models=w.retrieval.signature(e.ROOT)
  units=w.tree_units(self.detail['rows'])
  for u in units:
   u['promptSignature']=w.unit_signature(u,cfg,'Review',source,'',models)
   saved=r.read(self.path/'sections'/f'{u["id"]}.json')
   pre=w.prepare_unit(e,self.path,{'config':cfg,'topic':'Review'},u,saved['evidence'])
   saved['signature']=w.unit_signature(u,cfg,'Review',source,w.profile_signature(PROFILE),models,pre['hash'])
   e.write_json(self.path/'sections'/f'{u["id"]}.json',saved)
  return units
 def test_resume_after_model_switch_only_schedules_missing_units(self):
  units=self.prepare_seeded_units();missing=units[-1]
  (self.path/'review_parts'/f'section_{missing["serial"]}.json').unlink()
  retained={p:p.read_bytes() for p in (self.path/'sections').glob('*.json')}
  changed={**PROFILE,'provider':'opencode_go','model':'new-model','endpoint':'https://new.example/v1','reasoningByModel':{'new-model':'high'}}
  for op in ('start','retry'):
   e.write_json(self.path/'writing-job.json',{'state':'cancelled','mode':'write','items':{missing['id']:{'state':'cancelled'}}})
   with patch.object(r,'profile',return_value=changed),patch.object(w.subprocess,'Popen') as proc:
    proc.return_value.pid=os.getpid();result=w.rpc(e,'Test',op,{})
   self.assertEqual(result['completed'],3);self.assertEqual(result['latest'],0)
   self.assertEqual(result['stages']['writing'],{'state':'partial','completed':6,'total':7})
   self.assertEqual(list(result['job']['items']),[missing['id']])
  self.assertTrue(all(p.read_bytes()==content for p,content in retained.items()))
 def test_complete_mixed_model_body_is_not_a_draft_or_rewritten(self):
  self.prepare_seeded_units()
  before={p:p.read_bytes() for p in (self.path/'sections').glob('*.json')}
  with patch.object(r,'profile',return_value={**PROFILE,'model':'other-model'}):
   state=self.status();self.assertEqual(state['completed'],4);self.assertEqual(state['latest'],0)
   self.assertEqual(state['stages']['writing'],{'state':'complete','completed':7,'total':7})
   self.assertTrue(all(u['completed'] and u['state']=='done' for u in state['units']))
   with patch.object(w.subprocess,'Popen') as spawn:
    w.rpc(e,'Test','start',{});w.rpc(e,'Test','retry',{});spawn.assert_not_called()
   self.assertNotIn('草稿：',w.rpc(e,'Test','preview',{})['markdown'])
   self.assertFalse(w.export(e,'Test','md')['partial'])
  self.assertTrue(all(p.read_bytes()==content for p,content in before.items()))
 def test_explicit_rewrite_still_replaces_selected_complete_units(self):
  units=self.prepare_seeded_units();selected=[units[0]['id']]
  with patch.object(r,'profile',return_value={**PROFILE,'model':'other-model'}),patch.object(w.subprocess,'Popen') as spawn:
   spawn.return_value.pid=os.getpid();state=w.rpc(e,'Test','start',{'unitIds':selected})
  self.assertEqual(list(state['job']['items']),selected)
 def test_resume_keeps_material_guards_and_detects_incomplete_body(self):
  units=self.prepare_seeded_units();u=units[-1]
  internal=self.path/'sections'/f'{u["id"]}.json';saved=r.read(internal);saved['sections'][0]['markdown']=''
  e.write_json(internal,saved);e.write_json(self.path/'review_parts'/f'section_{u["serial"]}.json',w.review_format.public_part(u,saved['sections'],saved['evidence']))
  self.assertEqual(self.status()['completed'],3)
  with patch.object(w.subprocess,'Popen') as spawn:
   spawn.return_value.pid=os.getpid();state=w.rpc(e,'Test','start',{})
  self.assertEqual(list(state['job']['items']),[u['id']])
  e.write_json(self.path/'writing-job.json',{'state':'cancelled'})
  (self.path/'prompts'/f'{u["id"]}.json').unlink()
  with patch.object(w.subprocess,'Popen') as spawn:
   with self.assertRaisesRegex(ValueError,'准备完整'):w.rpc(e,'Test','start',{})
   spawn.assert_not_called()
 def test_frozen_materials_survive_project_model_and_key_change(self):
  import vector_service as v,embedding_profiles as profiles,project_embedding as binding,retrieval_settings as settings
  old={**v.DEFAULTS,'id':'a','name':'A','baseUrl':'https://a.example/v1','model':'model-a','apiKey':'fixture-secret'}
  new={**old,'id':'b','name':'B','baseUrl':'https://b.example/v1','model':'model-b'}
  profiles.write(e,{'profiles':[old,new],'activeProfile':'a'});binding.bind(e,old)
  cfg=w.config(self.path);rcfg=settings.snapshot(e.ROOT,e.PROJECT);source=w.source_signature(e);models=w.retrieval.signature(e.ROOT,rcfg)
  rows=self.detail['rows'];ctx=w.manuscripts.new_round(e,'Test',rows,'Review',cfg)
  ctx['materialSnapshot']={'sourceSignature':source,'modelsSignature':models,'retrieval':rcfg};e.write_json(self.path/'writing-round.json',ctx)
  for u in w.tree_units(rows):
   u['promptSignature']=w.unit_signature(u,cfg,'Review',source,'',models)
   evidence={n['id']:{'query':n['title'],'topK':7,'retrieval':rcfg,'chunks':[{'id':'c','text':'Evidence','metadata':{'pmid':'123','title':'Evidence','sourceKind':'pubmed_abstract','sectionPath':[]}}]} for n in u['leaves']}
   w.prepare_unit(e,self.path,{'config':cfg,'topic':'Review','retrieval':rcfg},u,evidence)
  self.assertEqual(self.status()['stages']['preparation']['state'],'ready')
  profiles.save(e,{**old,'apiKey':'rotated-key','rpm':100,'tpm':100000})
  self.assertEqual(self.status()['prepared'],4)
  binding.bind(e,new)
  e.write_json(self.base/'metadata/index-generation.json',{'generation':'rebuilt-with-B'})
  state=self.status();self.assertEqual(state['prepared'],4);self.assertTrue(state['materialModelChanged']);self.assertEqual(state['materialModel'],'model-a')
  with patch.object(w.subprocess,'Popen') as proc:
   proc.return_value.pid=os.getpid();w.rpc(e,'Test','start',{})
  token=r.read(self.path/'writing-job.json')['token']
  async def answer(profile,messages,cancelled,progress=lambda **kw:None):
   output=json.loads(messages[-1]['content'])['outputContract']
   return json.dumps({**output,'sections':[{**n,'blocks':[{'type':'markdown','text':'Frozen evidence'}]} for n in output['sections']]})
  with patch.object(w,'chat',side_effect=answer),patch.object(w.retrieval,'corpus',side_effect=AssertionError('Writing cannot recall')):
   asyncio.run(w.run(e,'Test',token))
  self.assertEqual(self.status()['latest'],4);self.assertEqual(len(w.manuscripts.listing(e,'Test')),1)
  # Old writing-round files gain provenance from verified historical inputs, without migration writes.
  old_round=r.read(self.path/'writing-round.json');old_round.pop('materialSnapshot')
  e.write_json(self.path/'writing-round.json',old_round);before=(self.path/'writing-round.json').read_bytes()
  recovered=self.status();self.assertEqual(recovered['prepared'],4);self.assertEqual(recovered['materialModel'],'model-a')
  self.assertEqual((self.path/'writing-round.json').read_bytes(),before)
  prompt=next((self.path/'prompts').glob('*.json'));original=prompt.read_bytes();prompt.write_text('{broken')
  self.assertEqual(self.status()['prepared'],3);prompt.write_bytes(original)
  value=r.read(prompt);value['evidenceHash']='invalid';e.write_json(prompt,value)
  self.assertEqual(self.status()['prepared'],3);prompt.write_bytes(original)
  # Missing one material package must block every write, including a selected group.
  (self.path/'review_parts'/'prompt_section_1.1.json').unlink()
  with self.assertRaisesRegex(ValueError,'全部章节'):w.rpc(e,'Test','start',{'unitIds':[w.tree_units(rows)[-1]['id']]})
  runtime=w.runtime(e,{});runtime.parent.mkdir(parents=True);runtime.touch()
  with patch.object(w.retrieval,'ready',return_value=True),self.assertRaisesRegex(ValueError,'不能混用'):
   w.rpc(e,'Test','prepare.resume',{})
 def test_preparation_zero_hits_is_not_ready(self):
  token=self.setup_run()
  class EmptyRetriever:
   def __init__(self,*args):pass
   def retrieve(self,*args):return []
  with patch.object(w.retrieval,'corpus',return_value=[]):asyncio.run(w.run(e,'Test',token,EmptyRetriever))
  state=self.status();self.assertEqual(state['prepared'],0);self.assertEqual(state['stages']['preparation']['state'],'partial')
  self.assertEqual(state['stages']['preparation']['completed'],0)
if __name__=='__main__':unittest.main()
