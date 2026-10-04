import asyncio,json,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,qa_service as q,qa_protocol as protocol,storage

DSML='<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="section"><｜｜DSML｜｜ parameter name="pmid" string="true">123</｜｜DSML｜｜ parameter><｜｜DSML｜｜ parameter name="section" string="true"></｜｜DSML｜｜ parameter><｜｜DSML｜｜ parameter name="offset" string="false">0</｜｜DSML｜｜ parameter></｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>'
class ProtocolTests(unittest.TestCase):
 def test_complete_dsml_only_becomes_validatable_actions(self):
  v,n=protocol.parse(DSML,'判断证据缺口',{'question':'Question'})
  self.assertFalse(v['enough']);self.assertTrue(n);self.assertEqual(q.validate_tool(v['tools'][0]),{'tool':'section','pmid':'123','section':'','offset':0})
  v,_=protocol.parse(DSML.replace('name="section"','name="shell"',1),'判断证据缺口',{})
  with self.assertRaises(q.ToolInputError):q.validate_tool(v['tools'][0])
  with self.assertRaises(protocol.ProtocolError):protocol.parse(DSML,'整理证据',{})
 def test_dsml_incomplete_or_ambiguous_parameters_are_not_executed(self):
  values=[DSML[:-10],DSML.replace('string="false">0','string="false">NaN'),DSML.replace('name="offset"','name="pmid"'),DSML+' extra','<!DOCTYPE calls>'+DSML,DSML.replace('string="true"','string="other"',1)]
  for text in values:
   with self.subTest(text=text),self.assertRaises(protocol.ProtocolError):protocol.parse(text,'判断证据缺口',{})
 def test_adapted_tools_still_obey_per_round_budget(self):
  value,_=protocol.parse(DSML,'判断证据缺口',{})
  value['tools']*=7
  normalized,issues=q.retrieval_plan(value,{'queriesPerRound':3,'toolsPerRound':6})
  self.assertEqual(len(normalized['tools']),6);self.assertEqual(issues[0]['input']['omittedCount'],1)
 def test_json_envelope_without_semantic_repair(self):
  value={'enough':False,'coverage':[],'queries':[],'tools':[]};raw=json.dumps(value)
  for text in (raw,'```json\n'+raw+'\n```','结果如下：\n'+raw+'\n结束。'):
   self.assertEqual(protocol.parse(text,'判断证据缺口',{})[0],value)
 def test_truncated_nested_duplicate_or_multiple_objects_never_salvaged(self):
  values=['{"outer":{"enough":true}', '{"enough":true,"enough":false,"coverage":[]}', '{"enough":NaN,"coverage":[]}', '{}\n{}','说明 {"outer":{"enough":true}', '[{"enough":true,"coverage":[]}]']
  for text in values:
   with self.subTest(text=text),self.assertRaises(protocol.ProtocolError):protocol.parse(text,'判断证据缺口',{})
 def test_stage_contracts_reject_wrong_types(self):
  for stage,value in [('规划问题',{'aspects':'text'}),('判断证据缺口',{'enough':'false','coverage':[]}),('回答前核对',{'enough':True,'coverage':{}}),('整理证据',{'findings':{}}),('判断证据缺口',{'enough':True,'coverage':[{'aspect':'x','status':'supported','gap':{}}]})]:
   with self.subTest(stage=stage),self.assertRaises(protocol.ProtocolError):protocol.parse(json.dumps(value),stage,{})
 def test_fallback_never_asserts_sufficient_or_verified(self):
  for stage in ('判断证据缺口','回答前核对'):self.assertIs(protocol.fallback(stage,{})['enough'],False)
  self.assertIsNone(protocol.fallback('核对引用原文',{}))
  self.assertEqual(protocol.fallback('规划问题',{'question':'NOT X?'})['queries'][0]['query'],'NOT X?')
 def test_raw_evidence_remains_usable_without_model_findings(self):
  rows=[{'eid':f'E{i+1}','text':'Exact original. '*2000,'metadata':{'pmid':str(i),'title':'Study','sourceKind':'fulltext'}} for i in range(20)]
  material,compact,omitted=q.answer_material(rows,[],12000)
  self.assertTrue(material);self.assertFalse(compact);self.assertEqual(omitted,[])
  self.assertEqual(len(material)+len(omitted),20)
  self.assertTrue(all(rows[int(v['eid'][1:])-1]['text']==v['text'] for v in material))
  self.assertEqual(rows[0]['text'],'Exact original. '*2000)

class RecoveryTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test';storage.project_dir(e.ROOT,e.PROJECT)
  self.record={'id':'chunk','text':'Original evidence.','metadata':{'pmid':'123','title':'Study','sourceKind':'fulltext','sectionPath':['Results']}}
  self.requests=[];self.mutated=False
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def execute(self,mode,verify=False,repair_seconds=60):
  rid=uuid.uuid4().hex;path=q.runpath(e,rid)
  cfg=q.config(e,{'verifyAnswer':verify,'maxRounds':3})
  snapshot={'id':rid,'config':cfg,'question':'Original question','pmids':None,'history':[],'sourceSignature':'x','embeddingFingerprint':'x','plannerSignature':'x','answerSignature':'x'}
  e.write_json(path/'input.json',snapshot);e.write_json(path/'job.json',{'id':rid,'events':[],'round':0,'answer':''})
  async def model(profile,messages,cancelled,progress,on_text,on_reasoning=None):
   system=messages[0]['content'];payload=json.loads(messages[-1]['content']);repair='这是格式修复请求' in system
   task=payload['task'] if repair else payload
   if '"aspects"' in system:stage='plan';result={'aspects':['Test'],'queries':[],'tools':[{'tool':'exact','text':'Original'}]}
   elif '"findings"' in system:stage='extract';result={'findings':[{'eid':'E1','quote':'Original evidence.','finding':'Test'}]}
   elif '"coverage"' in system:stage='decision';result={'enough':True,'coverage':[],'queries':[],'tools':[],'reason':'Enough'}
   elif '核对 draft' in system:stage='audit';result={'problems':[]}
   else:stage='answer';result='Answer with limits [E1]'
   self.requests.append((stage,repair,task))
   if mode=='network' and stage=='decision':raise ValueError('模型请求失败（HTTP 401）')
   if repair and mode=='cancel':raise q.Cancelled('已取消')
   if repair and mode=='mutation':
    self.mutated=True;e.atomic(storage.project_dir(e.ROOT,e.PROJECT)/'pubmed/current.xml','<PubmedArticleSet/>')
   if repair and mode=='timeout':await asyncio.sleep(.3)
   if mode=='dsml' and stage=='decision' and task['agentStep']==1:result=DSML
   if mode=='repair_once' and stage=='decision' and not repair:result='broken'
   if mode in ('fallback','cancel','mutation','timeout') and stage=='decision':result='broken'
   if mode=='all_bad' and stage!='answer':result='broken'
   if mode=='bad_audit' and stage=='audit':result='broken'
   text=result if isinstance(result,str) else json.dumps(result);on_text(text);return text
  def search(tools,queries):return [{'query':query,'hits':[{'eid':tools.add(self.record),'score':1.}]} for query in queries]
  with patch.object(q,'chat',side_effect=model),patch.object(q,'PROTOCOL_REPAIR_SECONDS',repair_seconds),patch.object(q,'current_signature',side_effect=lambda _: 'changed' if self.mutated else 'x'),patch.object(q,'profile_signature',return_value='x'),patch.object(q,'models',return_value=({'model':'mock'},{'model':'mock'})),patch.object(q.retrieval_settings,'fingerprint',return_value='x'),patch.object(q,'corpus',return_value=([self.record],{},[{'pmid':'123','title':'Study'}],{})),patch.object(q.EvidenceTools,'search',search):
   asyncio.run(q.run(e,rid))
  return q.read(path/'job.json')
 def test_dsml_keeps_retrieval_loop_no_extra_repair_request(self):
  j=self.execute('dsml');self.assertEqual(j['state'],'done');self.assertEqual(j['round'],0);self.assertEqual(j['agentStep'],2)
  self.assertTrue(any(v['type']=='protocol' and 'DSML' in v.get('reason','') for v in j['events']));self.assertFalse(any(r[1] for r in self.requests))
 def test_one_repair_continues_same_run_without_repeating_retrieval(self):
  j=self.execute('repair_once');self.assertEqual(j['state'],'done');self.assertEqual(sum(r[1] for r in self.requests),1);self.assertFalse(j.get('qualityWarnings'))
  self.assertEqual(sum(v['type']=='tool' for v in j['events']),1)
 def test_failed_decision_preserves_evidence_and_marks_limited_answer(self):
  j=self.execute('fallback');self.assertEqual(j['state'],'done');self.assertIn('[E1]',j['answer']);self.assertTrue(j['qualityWarnings']);self.assertIn('充足性未确认',j['stopReason'])
  answer=next(r[2] for r in self.requests if r[0]=='answer');self.assertEqual(answer['evidence'][0]['text'],self.record['text']);self.assertTrue(answer['qualityWarnings'])
 def test_global_repair_budget_and_original_question_fallback(self):
  j=self.execute('all_bad');self.assertEqual(j['state'],'done');self.assertEqual(sum(r[1] for r in self.requests),2);self.assertEqual(j['round'],1)
  self.assertTrue(any(v.get('query')=='Original question' for v in j['events']));self.assertEqual(next(r[2] for r in self.requests if r[0]=='answer')['findings'],[])
 def test_repair_timeout_does_not_lose_answer_or_loop(self):
  j=self.execute('timeout',repair_seconds=.12);self.assertEqual(j['state'],'done');self.assertTrue(j['qualityWarnings']);self.assertEqual(sum(r[1] for r in self.requests),1)
 def test_original_transport_failure_is_not_protocol_recovery(self):
  j=self.execute('network');self.assertEqual(j['state'],'failed');self.assertIn('401',j['error']);self.assertFalse(any(r[1] for r in self.requests))
 def test_cancel_and_source_change_during_repair_block_answer(self):
  for mode,state in [('cancel','cancelled'),('mutation','failed')]:
   self.requests=[];self.mutated=False;j=self.execute(mode);self.assertEqual(j['state'],state);self.assertFalse(j['answer']);self.assertFalse(any(r[0]=='answer' for r in self.requests))
 def test_retired_audit_is_not_called_even_with_legacy_config(self):
  j=self.execute('bad_audit',verify=True);self.assertEqual(j['state'],'done');self.assertEqual(j['citationValidation']['status'],'structural_checked');self.assertIn('[E1]',j['answer']);self.assertFalse(any(r[0]=='audit' for r in self.requests))

if __name__=='__main__':unittest.main()
