import json,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,qa_service as q,storage,vector_chunks as chunks

class QATests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test';self.base=storage.project_dir(e.ROOT,e.PROJECT)
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def test_round_settings_reject_invalid_values(self):
  for value in ({'topK':True},{'maxRounds':0},{'minRounds':4,'maxRounds':3},{'queriesPerRound':1.2},{'contextChars':100}):
   with self.subTest(value=value),self.assertRaises(ValueError):q.config(e,value)
  self.assertEqual(q.config(e)['maxRounds'],3);self.assertEqual(q.config(e,{'topK':100})['topK'],100)
 def test_removed_fulltext_setting_is_ignored(self):
  self.assertNotIn('fulltextEnabled',q.config(e,{'fulltextEnabled':True}))
 def test_legacy_provider_and_explicit_models_share_parameters(self):
  import sqlite3,review_service
  path=e.ROOT/'data/research/research.sqlite3';path.parent.mkdir(parents=True)
  provider={'id':'p','model':'pro','baseUrl':'http://localhost:9000/v1','apiKey':'test-only','temperature':.7,'timeout':120}
  with sqlite3.connect(path) as c:
   c.execute('CREATE TABLE settings(key TEXT,value TEXT)');c.executemany('INSERT INTO settings VALUES(?,?)',[('profiles',json.dumps([provider])),('activeProfile','"p"')])
  a,b=q.models(e,q.config(e));self.assertEqual(a,b);self.assertEqual(a['model'],'pro')
  with self.assertRaises(ValueError):review_service.profile(e,'p','flash')
  provider['models']=['flash','pro']
  with sqlite3.connect(path) as c:c.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps([provider]),'profiles'))
  a,b=q.models(e,q.config(e,{'plannerProfile':'p','plannerModel':'flash'}));self.assertEqual(a['model'],'flash');self.assertEqual(b['model'],'pro');self.assertEqual(a['temperature'],b['temperature']);self.assertEqual(a['apiKey'],b['apiKey'])
 def test_scope_and_tool_boundaries(self):
  def record(i,p):return {'id':str(i),'text':'Exact marker evidence '+str(i),'metadata':{'pmid':p,'title':'Title','sourceKind':'fulltext','sectionPath':['Results'],'previousChunkId':str(i-1) if i else None,'nextChunkId':str(i+1)}}
  records=[record(i,'123') for i in range(12)];items={}
  def add(r):
   eid='E'+str(int(r['id'])+1);items[eid]=r;return eid
  tools=q.EvidenceTools(records,{},[{'pmid':'123','title':'Title'}],q.config(e),e,lambda:None,add);tools.evidence=items
  a=tools.execute({'tool':'section','pmid':'123','section':'Results'});self.assertEqual(len(a['evidenceIds']),8);self.assertEqual(a['nextOffset'],8)
  b=tools.execute({'tool':'section','pmid':'123','section':'Results','offset':8});self.assertEqual(len(b['evidenceIds']),4);self.assertIsNone(b['nextOffset'])
  self.assertEqual(tools.execute({'tool':'exact','text':'marker','pmid':'123'})['total'],12)
  for action in ({'tool':'section','pmid':'999'},{'tool':'shell'},{'tool':'neighbors','evidenceId':'E999'},{'tool':'papers','offset':-1}):
   with self.subTest(action=action),self.assertRaises(ValueError):tools.execute(action)
 def test_duplicate_queries_do_not_consume_new_round(self):
  seen=set();a=q.clean_queries([{'query':' Gene X ','purpose':'first'},{'query':'gene   x','purpose':'again'}],3,seen)
  self.assertEqual(len(a),1);self.assertEqual(q.clean_queries([{'query':'GENE X'}],3,seen),[])
 def test_invalid_tool_arguments_are_recoverable_and_never_coerced_to_searches(self):
  for action in ('exact',None,[],{'tool':[]},{'tool':'unknown'},{'tool':'exact'},{'tool':'exact','text':[]},
                 {'tool':'exact','text':'x','pmid':['123']},{'tool':'exact','text':'x','offset':True},
                 {'tool':'exact','text':'x','offset':-1},{'tool':'neighbors','evidenceId':{}},
                 {'tool':'section','pmid':'可选'},{'tool':'papers','text':{}},{'tool':'papers','url':'https://example.com'}):
   with self.subTest(action=action),self.assertRaises(q.ToolInputError):q.validate_tool(action)
  self.assertEqual(q.validate_tool({'tool':'exact','text':'perforin','pmid':123,'offset':'0'}),{'tool':'exact','text':'perforin','pmid':'123','offset':0})
  self.assertEqual(q.validate_tool({'tool':'papers','text':None}),{'tool':'papers','text':'','offset':0})
 def test_actual_bare_tool_response_preserves_all_queries_and_reports_missing_parameter(self):
  plan={'queries':[{'query':s,'purpose':'locate evidence'} for s in ('natural killer','degranulation','perforin')],'tools':['exact']}
  normalized,issues=q.retrieval_plan(plan,q.config(e))
  self.assertEqual(normalized['queries'],plan['queries']);self.assertEqual(normalized['tools'],[])
  self.assertEqual(issues[0]['input'],'exact');self.assertIn('text',issues[0]['error']);self.assertEqual(plan['tools'],['exact'])
 def test_mixed_requests_and_null_containers_do_not_discard_valid_siblings(self):
  cfg=q.config(e,{'queriesPerRound':5})
  value,issues=q.retrieval_plan({'queries':[None,{'query':['bad']},'valid query',{'query':'other','purpose':'why'}],'tools':[None,{'tool':'neighbors','evidenceId':[]},{'tool':'papers'}]},cfg)
  self.assertEqual([v['query'] for v in value['queries']],['valid query','other']);self.assertEqual(value['tools'],[{'tool':'papers','text':'','offset':0}]);self.assertEqual(len(issues),4)
  self.assertEqual(q.retrieval_plan({'queries':None,'tools':None},cfg),({'queries':[],'tools':[]},[]))
  value,issues=q.retrieval_plan({'queries':{'query':'single'},'tools':{'tool':'exact','text':'marker'}},cfg)
  self.assertEqual(value['queries'][0]['query'],'single');self.assertEqual(value['tools'][0]['text'],'marker');self.assertFalse(issues)
 def test_tool_parameter_recovery_does_not_swallow_source_change_or_cancellation(self):
  for error in (ValueError('source changed'),q.Cancelled('cancelled')):
   def check():raise error
   tools=q.EvidenceTools([],{},[],q.config(e),e,check,lambda r:'E1')
   with self.assertRaises(type(error)) as caught:tools.execute({'tool':'papers'})
   self.assertIs(caught.exception,error);self.assertNotIsInstance(caught.exception,q.ToolInputError)
 def test_unknown_evidence_and_out_of_scope_pmid_are_recoverable_without_reading(self):
  tools=q.EvidenceTools([],{},[{'pmid':'123','title':'Study'}],q.config(e),e,lambda:None,lambda r:self.fail('must not add'))
  for action in ({'tool':'neighbors','evidenceId':'E999'},{'tool':'section','pmid':'999'},{'tool':'exact','text':'marker','pmid':'999'}):
   with self.subTest(action=action),self.assertRaises(q.ToolInputError):tools.execute(action)
 def test_citation_scope_and_missing_citation(self):
  evidence=[{'eid':'E1'}];self.assertEqual(q.citations('Body [E1]',evidence),['E1'])
  for text in ('Body [E999]','Body','Body (PMID: 123) [E1]'):
   with self.subTest(text=text),self.assertRaises(ValueError):q.citations(text,evidence)
  self.assertEqual(q.citations('论文 PMID: 123',[],['123']),[])
  with self.assertRaises(ValueError):q.citations('论文 PMID: 999',[],['123'])
 def test_section_labels_do_not_apply_secondary_cleaning(self):
  self.assertTrue(q.evidence_allowed({'text':'Retained text.','metadata':{'blockType':'paragraph','sectionPath':['8. References']}}))
  self.assertFalse(q.evidence_allowed({'text':'  '}))
  self.assertTrue(q.evidence_allowed({'metadata':{'blockType':'paragraph','sectionPath':['Results']},'text':'The author references another result.'}))
 def test_quote_reconciliation_preserves_original_span(self):
  source='table: neutrophil level <1.0<br>109/L; study  NO\n  increase.'
  for quote,expected in [('Neutrophil level <1.0<br>109/L','neutrophil level <1.0<br>109/L'),('study NO increase','study  NO\n  increase')]:
   match=q.quote_match(quote,source);self.assertEqual(match['quote'],expected);self.assertEqual(source[match['start']:match['start']+len(expected)],expected)
  for altered in ('neutrophil level >1.0<br>109/L','neutrophil level <10<br>109/L','study increase','neutrophil level <1.0 109/L'):
   self.assertIsNone(q.quote_match(altered,source))
  self.assertIsNone(q.quote_match('10⁹/L','109/L'))
 def test_bad_quote_keeps_valid_findings(self):
  accepted,rejected,corrected=q.validate_findings([{'eid':'E1','quote':'Neutrophil','finding':'cell'}, {'eid':'E2','quote':'invented result'}, {'eid':[],'quote':'bad'}, {'eid':'E1','quote':'neutrophil','finding':[]}],[{'eid':'E1','text':'neutrophil'}, {'eid':'E2','text':'No change.'}])
  self.assertEqual(len(accepted),1);self.assertEqual(len(rejected),3);self.assertEqual(corrected,['E1']);self.assertEqual(accepted[0]['quote'],'neutrophil')
 def test_no_secondary_section_cleaning(self):
  self.assertTrue(q.evidence_allowed({'metadata':{'sectionPath':['**REFERENCES AND NOTES**']},'text':'**Acknowledgments:** We thank staff'}))
  self.assertTrue(q.evidence_allowed({'metadata':{'sectionPath':['Article']},'text':'**Acknowledgments:** We thank staff'}))
  self.assertTrue(q.evidence_allowed({'metadata':{'sectionPath':['Results']},'text':'Funding constraints may affect outcomes.'}))
 def test_retired_audit_setting_never_causes_extra_model_calls(self):
  import asyncio
  self.assertNotIn('verifyAnswer',q.config(e))
  self.assertNotIn('verifyAnswer',q.config(e,{'verifyAnswer':True}))
  rid=uuid.uuid4().hex;path=q.runpath(e,rid);cfg=q.config(e,{'verifyAnswer':True,'maxRounds':1})
  snapshot={'id':rid,'config':cfg,'question':'Test','pmids':None,'history':[],'sourceSignature':'x','embeddingFingerprint':'x','plannerSignature':'x','answerSignature':'x'}
  e.write_json(path/'input.json',snapshot);e.write_json(path/'job.json',{'id':rid,'events':[],'round':0,'answer':''})
  record={'id':'chunk','text':'Original evidence.','metadata':{'pmid':'123','title':'Study','sourceKind':'fulltext','sectionPath':['Results']}}
  async def model(profile,messages,cancelled,progress,on_text,on_reasoning=None):
   if on_reasoning:on_reasoning('Checking supplied evidence.')
   sys=messages[0]['content']
   if '"aspects"' in sys:value={'aspects':['Test'],'queries':[],'tools':[{'tool':'exact','text':'Original'}]}
   elif '"findings"' in sys:value={'findings':[{'eid':'E1','quote':'Original evidence.','finding':'Test'}]}
   elif '"coverage"' in sys:value={'enough':True,'coverage':[],'queries':[],'tools':[],'reason':'enough'}
   elif '核对 draft' in sys:raise AssertionError('retired audit must not run')
   else:on_text('Answer [E1]');return 'Answer [E1]'
   return json.dumps(value)
  with patch.object(q,'chat',side_effect=model),patch.object(q,'current_signature',return_value='x'),patch.object(q,'profile_signature',return_value='x'),patch.object(q,'models',return_value=({'model':'mock'},{'model':'mock'})),patch.object(q.retrieval_settings,'fingerprint',return_value='x'),patch.object(q,'corpus',return_value=([record],{},[{'pmid':'123','title':'Study'}],{})):
   asyncio.run(q.run(e,rid))
  job=q.read(path/'job.json');self.assertEqual(job['state'],'done');self.assertEqual(job['answer'],'Answer [E1]');self.assertEqual(job['citationValidation']['status'],'structural_checked')
  self.assertNotIn('auditStarted',job)
  self.assertTrue(all(v.get('reasoning')=='Checking supplied evidence.' for v in job['events'] if v['type']=='model'))
  self.assertTrue(list(path.glob('*.reasoning.txt')))

 def test_read_inventory_never_builds_chunks(self):
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Study</ArticleTitle><Abstract><AbstractText>'+('Evidence text. '*30)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
  with patch.object(chunks,'sync',side_effect=AssertionError('must not sync')):
   records,cached,papers,coverage=q.corpus(e)
  self.assertFalse(records);self.assertFalse(cached);self.assertEqual(coverage['papers'],1);self.assertEqual(papers[0]['searchableChunks'],0)
  self.assertFalse((self.base/'vectors/chunks.sqlite3').exists())
  e.write_json(self.base/'metadata/index-cleared.json',{'cleared':True})
  self.assertEqual(q.corpus(e)[3]['papers'],1)
  self.assertFalse((self.base/'vectors/chunks.sqlite3').exists())
 def test_source_version_changes_and_missing_cache_is_excluded(self):
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Study</ArticleTitle><Abstract><AbstractText>'+('Evidence text. '*30)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
  chunks.sync(e);signature=q.current_signature(e);self.assertTrue(q.corpus(e)[0])
  path=self.base/'pubmed/current.xml';path.write_text(path.read_text().replace('Evidence text','Changed text'))
  self.assertNotEqual(q.current_signature(e),signature);self.assertFalse(q.corpus(e)[0])
 def test_ident_and_symlink_protection(self):
  for ident in ('../other','abc',None):
   with self.assertRaises(ValueError):q.runpath(e,ident)
  self.base.mkdir(parents=True,exist_ok=True)
  (self.base/'qa').symlink_to(e.ROOT/'tmp')
  with self.assertRaises(ValueError):q.root(e)
 def test_cancel_targets_only_current_project_run(self):
  rid=uuid.uuid4().hex;qpath=q.runpath(e,rid)
  import os,time
  e.write_json(q.root(e)/'active.json',{'id':rid});e.write_json(qpath/'job.json',{'id':rid,'state':'running','pid':os.getpid(),'created':time.time()})
  q.rpc(e,'cancel',{'runId':uuid.uuid4().hex});self.assertFalse((qpath/'cancel').exists())
  q.rpc(e,'cancel',{'runId':rid});self.assertTrue((qpath/'cancel').exists());self.assertEqual(q.job(e)['state'],'stopping')
 def test_thread_branches_rename_delete_preserve_evidence_and_history(self):
  t=q.rpc(e,'new',{});ids=[uuid.uuid4().hex for _ in range(3)]
  for i,rid in enumerate(ids):
   e.write_json(q.runpath(e,rid)/'job.json',{'id':rid,'threadId':t['id'],'state':'done','question':f'Q{i}','answer':f'A{i}','events':[]})
   e.write_json(q.runpath(e,rid)/'evidence.json',[])
  t['runIds']=ids;e.write_json(q.threadpath(e,t['id']),t)
  branch=q.rpc(e,'fork',{'threadId':t['id'],'keepCount':2});self.assertEqual(branch['runIds'],ids[:2]);self.assertEqual(branch['parentId'],t['id'])
  retry=q.rpc(e,'fork',{'threadId':t['id'],'keepCount':1});self.assertEqual(retry['runIds'],ids[:1])
  for count in (-1,4,True,None):
   with self.assertRaises(ValueError):q.rpc(e,'fork',{'threadId':t['id'],'keepCount':count})
  q.rpc(e,'rename',{'threadId':branch['id'],'name':'New name'});self.assertEqual(q.thread(e,branch['id'])['name'],'New name')
  with self.assertRaises(ValueError):q.rpc(e,'rename',{'threadId':branch['id'],'name':' '})
  before=(q.runpath(e,ids[0])/'job.json').read_bytes();q.rpc(e,'delete',{'threadId':t['id']})
  self.assertNotIn(t['id'],[x['id'] for x in q.rpc(e,'list',{})]);self.assertEqual([r['answer'] for r in q.thread(e,branch['id'])['runs']],['A0','A1'])
  self.assertEqual((q.runpath(e,ids[0])/'job.json').read_bytes(),before)
  with self.assertRaises(ValueError):q.thread(e,t['id'])

if __name__=='__main__':unittest.main()
