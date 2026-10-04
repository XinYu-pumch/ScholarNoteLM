"""Cross-turn routing and evidence identity, without external providers."""
import copy,json,sys,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_qa_mini_review as harness
import qa_history,qa_service as q,qa_mini_review as mini,qa_protocol,engine as e

class ContextTests(unittest.TestCase):
 setUp=harness.MiniReviewTests.setUp
 tearDown=harness.MiniReviewTests.tearDown
 make_rows=harness.MiniReviewTests.make_rows
 execute=harness.MiniReviewTests.execute
 def seed(self,output=None):
  e.atomic(self.project/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID></MedlineCitation></PubmedArticle></PubmedArticleSet>')
  self.output=output or [{'type':'markdown','text':'Measured results [E3].'}]
  self.recall_count=len(self.rows)
  job,_,path=self.execute();self.assertEqual(job['state'],'done',job.get('error'))
  self.context=qa_history.collect(path.parent,[job['id']]);self.calls=[];self.searches=[];self.full_calls=[];self.output=None;self.recall_count=1
  self.history_requests=[{'tool':'read_previous_evidence','runId':job['id']}]
  return job,path
 def test_greeting_and_clarification_do_not_require_index_or_round_minimum(self):
  for route in ('chat','clarify'):
   self.route=route;self.no_queries=True;self.calls=[];self.searches=[]
   with patch.object(q.chunks,'sync',side_effect=AssertionError('no indexing')),patch.object(mini.retrieval,'ready',side_effect=AssertionError('no retrieval validation')):
    job,ev,_=self.execute({'minRounds':3})
   self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],0);self.assertEqual(ev,[]);self.assertFalse(self.searches)
   self.assertEqual(len(self.calls),2);self.assertEqual(job['citationValidation']['status'],'not_applicable')
 def test_rewrite_loads_only_cited_evidence_and_rebinds_source_block(self):
  old,path=self.seed();self.route='rewrite';self.no_queries=True
  job,ev,_=self.execute({'minRounds':3,'fulltextEnabled':True})
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],0);self.assertEqual(len(ev),1)
  self.assertEqual(ev[0]['id'],'chunk-2');self.assertEqual(ev[0]['eid'],'E1');self.assertFalse(self.searches);self.assertFalse(self.full_calls)
  source=self.calls[-1][1]['historyEvidence'][0]
  self.assertEqual(source['referenceMap'],{'E3':'E1'});self.assertEqual(source['sourceBlocks'][0]['text'],'Measured results [E1].')
  self.assertEqual(self.calls[-1][1]['history'],self.context)
  self.assertFalse(any('逐要点说明支持' in system for system,_,_ in self.calls))
 def test_history_evidence_can_answer_without_new_retrieval(self):
  self.seed();self.route='evidence';self.no_queries=True
  job,ev,_=self.execute({'minRounds':3})
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],0);self.assertEqual(len(ev),1);self.assertFalse(self.searches)
  assessment=next(p for s,p,_ in self.calls if '逐要点说明支持' in s);self.assertEqual(assessment['minRounds'],0)
 def test_grouped_history_and_adjacent_rewrite_need_no_format_repair(self):
  self.seed([{'type':'markdown','text':'Measured results [E1, E3].'}]);self.route='rewrite';self.no_queries=True
  self.output=[{'type':'markdown','text':'Shortened [E1][E2].'}]
  job,ev,_=self.execute({'minRounds':3})
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],0);self.assertFalse(self.searches)
  self.assertEqual(len(self.calls),2);self.assertEqual(len(job['citationRefs']),2)
  self.assertEqual(self.calls[-1][1]['historyEvidence'][0]['sourceBlocks'][0]['text'],'Measured results [E1] [E2].')
  self.assertEqual(job['answer'].count('(PMID: 123)'),1)
 def test_failed_rewrite_counts_material_sent_and_has_readable_error(self):
  self.seed();self.route='rewrite';self.no_queries=True
  self.output=[{'type':'markdown','text':'Invalid [E999].'}]
  job,ev,_=self.execute()
  self.assertEqual(job['state'],'failed');self.assertIn('回答格式需要修复',job['error']);self.assertEqual(job['formatRepair']['state'],'failed')
  self.assertEqual(job['readingCoverage']['examinedChunks'],len(ev));self.assertEqual(job['readingCoverage']['examinedPapers'],1)
 def test_history_and_new_retrieval_share_pool_without_id_collision(self):
  self.seed();self.route='research';self.no_queries=False
  # The old E3 is now E1; the newly retrieved original chunk becomes E2.
  job,ev,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'))
  self.assertEqual([r['id'] for r in ev],['chunk-2','chunk-0']);self.assertEqual([r['eid'] for r in ev],['E1','E2'])
  self.assertEqual(len(self.searches),1);self.assertEqual(self.calls[0][1]['history'],self.context)
 def test_same_snapshot_in_history_and_retrieval_is_deduplicated(self):
  self.seed([{'type':'markdown','text':'Result [E1].'}]);job,ev,_=self.execute()
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(len(ev),1)
 def test_incomplete_evidence_triggers_new_search_and_actual_minimum_rounds(self):
  self.seed();self.route='evidence';self.no_queries=True;self.enough=False
  job,_,_=self.execute({'minRounds':2,'maxRounds':2})
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],2);self.assertEqual(len(self.searches),2)
 def test_partial_coverage_does_not_override_models_sufficient_verdict(self):
  self.partial_coverage=True;self.new_queries=False
  job,_,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],1)
 def test_scope_and_uncited_ids_and_unknown_runs_cannot_leak(self):
  old,path=self.seed();request=self.history_requests[0]
  self.assertEqual(qa_history.load(path.parent,self.context,request,set())['rows'],[])
  for bad in ({**request,'referenceIds':['E4']},{**request,'runId':uuid.uuid4().hex},{**request,'runId':'../escape'}):
   with self.assertRaises(ValueError):qa_history.load(path.parent,self.context,bad,{'123'})
  self.route='rewrite';self.no_queries=True
  with patch.object(mini.files,'current',return_value=set()):job,ev,_=self.execute()
  self.assertEqual(job['state'],'failed');self.assertIn('无法安全改写',job['error']);self.assertFalse(ev)
 def test_structured_synthesized_table_is_rebound_and_retained(self):
  self.seed([{'type':'markdown','text':'见 {{ref:T1}} [E3].'},
             {'type':'table','table_id':'T1','title':'Results','columns':['Condition','Result'],'rows':[['Mice','No effect [E3]']],'notes':'Mice only.'}])
  self.route='rewrite';self.no_queries=True
  self.output=[{'type':'table','table_id':'T1','title':'简表','columns':['结果'],'rows':[['No effect [E1]']],'notes':'Mice only.'}]
  job,ev,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'))
  block=self.calls[-1][1]['historyEvidence'][0]['sourceBlocks'][1]
  self.assertEqual(block['rows'][0][1],'No effect [E1]');self.assertEqual(job['answerBlocks'][0]['type'],'table')
 def test_assessment_can_read_more_history_without_counting_search_rounds(self):
  old,_=self.seed([{'type':'markdown','text':'Two results [E1] [E3].'}])
  self.route='evidence';self.no_queries=True
  self.history_requests[0]['referenceIds']=['E1']
  self.extra_history=[{'tool':'read_previous_evidence','runId':old['id'],'referenceIds':['E3']}]
  job,ev,_=self.execute({'minRounds':3})
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],0);self.assertEqual(len(ev),2)
  self.assertEqual(sum('逐要点说明支持' in system for system,_,_ in self.calls),2);self.assertFalse(self.searches)
 def test_historical_figure_is_reloaded_as_real_visual_input(self):
  e.atomic(self.project/'markdown/assets/123/figure.png',harness.PNG)
  self.rows=self.make_rows('Context.\n\n![](assets/123/figure.png)\n\nCaption.')
  self.vision=True;self.seed([{'type':'resource','resource_id':'R1'}]);self.route='rewrite';self.no_queries=True
  self.output=[{'type':'resource','resource_id':'R1'}]
  job,_,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'));self.assertFalse(self.searches)
  self.assertEqual(sum(p['type']=='image_url' for p in self.calls[-1][2]),1)
  self.assertEqual(job['answerBlocks'][0]['kind'],'figure')
 def test_rewrite_cannot_add_an_uncited_associated_resource_reference(self):
  e.atomic(self.project/'markdown/assets/123/figure.png',harness.PNG)
  self.rows=self.make_rows('Context.\n\n![](assets/123/figure.png)\n\nCaption.')
  self.vision=True;self.seed([{'type':'markdown','text':'Original statement [E1].'}]);self.route='rewrite';self.no_queries=True
  self.output=[{'type':'markdown','text':'Added citation [R1].'}]
  job,_,_=self.execute();self.assertEqual(job['state'],'failed');self.assertIn('回答格式需要修复',job['error']);self.assertIn('纯改写不得新增',job['formatRepair']['reason'])
 def test_complete_history_excludes_failed_output_and_has_no_six_turn_cutoff(self):
  root=q.root(e)/'runs';ids=[]
  for i in range(9):
   rid=uuid.uuid4().hex;ids.append(rid)
   e.write_json(root/rid/'job.json',{'question':str(i),'state':'failed' if i==3 else 'done','answer':'Answer '+str(i),'draft':'bad draft','error':'network'})
  context=qa_history.collect(root,ids)
  self.assertEqual(len(context),9);self.assertEqual(context[0]['answer'],'Answer 0');self.assertEqual(context[3]['answer'],'')
  self.assertNotIn('bad draft',json.dumps(context));self.assertNotIn('network',json.dumps(context))
 def test_invalid_routing_contract_does_not_bypass_checks(self):
  base={'route':'chat','aspects':[],'queries':[],'historyRequests':[]}
  qa_protocol.validate(base,'拆解问答问题')
  for bad in ({**base,'route':'other'},{**base,'queries':[{'query':'scientific claim'}]},{**base,'route':'rewrite'},{**base,'historyRequests':[{'tool':'read_previous_evidence','runId':'../../'}]}):
   with self.assertRaises(ValueError):qa_protocol.validate(bad,'拆解问答问题')

if __name__=='__main__':unittest.main()
