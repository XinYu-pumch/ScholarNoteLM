"""Retry updates one message slot; immutable attempts and sibling threads survive."""
import sys,tempfile,unittest
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,qa_service as q,review_retrieval
REAL_JOB=q.job

class RetryTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'retry'
  self.stack=ExitStack();p={'model':'fixture'}
  for target,name,value in [(q,'models',(p,p)),(q,'evidence_model',p),(q,'current_signature','source'),(q,'profile_signature','model'),(q.retrieval_settings,'fingerprint','embed'),(q.retrieval_settings,'snapshot',{'method':'bm25'}),(review_retrieval,'ready',True),(review_retrieval,'signature','retrieval'),(q.chunks,'sync',None),(q,'corpus',([],{},[{'pmid':'123'}],{})),(q,'job',None)]:
   self.stack.enter_context(patch.object(target,name,return_value=value))
  self.spawn=self.stack.enter_context(patch.object(q.subprocess,'Popen',return_value=Mock(pid=123)))
  self.t=q.rpc(e,'new',{})
 def tearDown(self):self.stack.close();e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def add(self,question,state='done'):
  result=q.rpc(e,'start',{'threadId':self.t['id'],'question':question})
  path=q.runpath(e,result['id']);j=q.read(path/'job.json');j.update(state=state,answer='Answer to '+question)
  e.write_json(path/'job.json',j);e.write_json(path/'evidence.json',[])
  return result['id']
 def test_regenerate_replaces_middle_slot_preserves_history_logs_and_branch(self):
  ids=[self.add('First'),self.add('Retry me','failed'),self.add('Later')]
  branch=q.rpc(e,'fork',{'threadId':self.t['id'],'keepCount':3})
  old_path=q.runpath(e,ids[1]);old_bytes=(old_path/'job.json').read_bytes()
  result=q.rpc(e,'regenerate',{'threadId':self.t['id'],'runId':ids[1]});rid=result['id']
  self.assertEqual(q.thread(e,self.t['id'])['runIds'],[ids[0],rid,ids[2]])
  self.assertEqual(q.thread(e,branch['id'])['runIds'],ids)
  self.assertEqual(len(q.rpc(e,'list',{})),2)
  self.assertEqual((old_path/'job.json').read_bytes(),old_bytes)
  snapshot=q.read(q.runpath(e,rid)/'input.json');self.assertEqual([r['question'] for r in snapshot['history']],['First']);self.assertNotIn('resumeFrom',snapshot)
  job=q.public_job(e,rid);self.assertEqual(job['messageId'],ids[1]);self.assertEqual(job['attempt'],2);self.assertEqual(job['replacesRunId'],ids[1])
 def test_resume_reuses_original_context_without_appending_and_repeated_retry_keeps_slot(self):
  original=self.add('Question','failed');first_snapshot=q.read(q.runpath(e,original)/'input.json')
  result=q.rpc(e,'resume',{'threadId':self.t['id'],'runId':original});rid=result['id']
  self.assertEqual(q.thread(e,self.t['id'])['runIds'],[rid])
  snapshot=q.read(q.runpath(e,rid)/'input.json');self.assertEqual(snapshot['resumeFrom'],original);self.assertEqual(snapshot['history'],first_snapshot['history'])
  j=q.read(q.runpath(e,rid)/'job.json');j['state']='failed';e.write_json(q.runpath(e,rid)/'job.json',j)
  next_id=q.rpc(e,'regenerate',{'threadId':self.t['id'],'runId':rid})['id']
  self.assertEqual(q.thread(e,self.t['id'])['runIds'],[next_id]);self.assertEqual(q.public_job(e,next_id)['messageId'],original);self.assertEqual(q.public_job(e,next_id)['attempt'],3)
 def test_retry_rejects_stale_or_unrelated_target_without_spawning(self):
  rid=self.add('Question','failed');other=q.rpc(e,'new',{});count=self.spawn.call_count
  with self.assertRaises(ValueError):q.rpc(e,'regenerate',{'threadId':other['id'],'runId':rid})
  self.assertEqual(self.spawn.call_count,count);self.assertEqual(q.thread(e,other['id'])['runIds'],[])
 def test_copy_preserves_evidence_and_independent_retry_after_original_deleted(self):
  rid=self.add('Original','failed');path=q.runpath(e,rid)
  evidence=[{'eid':'E1','text':'Source snapshot','metadata':{'pmid':'123','title':'Fixture source','sourceKind':'fulltext'}}]
  e.write_json(path/'evidence.json',evidence)
  duplicate=q.rpc(e,'copy',{'threadId':self.t['id']})
  self.assertNotEqual(duplicate['id'],self.t['id']);self.assertEqual(duplicate['runIds'],[rid])
  q.rpc(e,'delete_many',{'threadIds':[self.t['id'],self.t['id']]})
  self.assertEqual([t['id'] for t in q.rpc(e,'list',{})],[duplicate['id']])
  self.assertEqual(q.rpc(e,'evidence',{'runId':rid,'evidenceId':'E1'}),evidence[0])
  new=q.rpc(e,'regenerate',{'threadId':duplicate['id'],'runId':rid})['id']
  self.assertEqual(q.thread(e,duplicate['id'])['runIds'],[new])
  self.assertEqual(q.read(q.threadpath(e,self.t['id']))['runIds'],[rid])
  self.assertEqual(q.read(path/'evidence.json'),evidence)
 def test_bulk_delete_validates_every_target_before_hiding_any_thread(self):
  second=q.rpc(e,'new',{})
  for ids in ([],[self.t['id'],None],[self.t['id'],'missing']):
   with self.assertRaises(ValueError):q.rpc(e,'delete_many',{'threadIds':ids})
  self.assertEqual(len(q.rpc(e,'list',{})),2)
  q.rpc(e,'delete_many',{'threadIds':[self.t['id'],second['id']]})
  self.assertEqual(q.rpc(e,'list',{}),[])
 def test_copy_keeps_formal_history_and_can_retrieve_cited_evidence_after_deletion(self):
  import qa_history
  rid=self.add('Human evidence');path=q.runpath(e,rid)
  j=q.read(path/'job.json');j['citationRefs']=[{'id':'E1','pmid':'123'}];e.write_json(path/'job.json',j)
  evidence=[{'id':'chunk-stable','eid':'E1','text':'Human cell experiment','metadata':{'pmid':'123','title':'Source','sourceKind':'fulltext'}}]
  e.write_json(path/'evidence.json',evidence)
  duplicate=q.rpc(e,'copy',{'threadId':self.t['id']});q.rpc(e,'delete_many',{'threadIds':[self.t['id']]})
  result=q.rpc(e,'start',{'threadId':duplicate['id'],'question':'What about mice?'})
  history=q.read(q.runpath(e,result['id'])/'input.json')['history']
  self.assertEqual(history[0]['question'],'Human evidence');self.assertEqual(history[0]['answer'],'Answer to Human evidence')
  loaded=qa_history.load(path.parent,history,{'runId':rid,'referenceIds':['E1']},{'123'})
  self.assertEqual(loaded['rows'],evidence)
 def test_active_shared_run_blocks_copy_and_batch_delete_without_partial_deletion(self):
  rid=self.add('Running','failed');second=q.rpc(e,'new',{})
  with patch.object(q,'job',return_value={'id':rid,'state':'running'}):
   with self.assertRaisesRegex(ValueError,'等待'):q.rpc(e,'copy',{'threadId':self.t['id']})
   with self.assertRaisesRegex(ValueError,'等待'):q.rpc(e,'delete_many',{'threadIds':[second['id'],self.t['id']]})
  self.assertEqual(len(q.rpc(e,'list',{})),2)
 def test_changed_configuration_rejects_resume_but_allows_regenerate_in_place(self):
  rid=self.add('Question','failed');q.rpc(e,'settings.save',{'topK':9})
  with self.assertRaisesRegex(ValueError,'无法继续检查点'):q.rpc(e,'resume',{'threadId':self.t['id'],'runId':rid})
  self.assertEqual(q.thread(e,self.t['id'])['runIds'],[rid])
  new=q.rpc(e,'regenerate',{'threadId':self.t['id'],'runId':rid})['id']
  self.assertEqual(q.thread(e,self.t['id'])['runIds'],[new]);self.assertEqual(q.read(q.runpath(e,new)/'input.json')['config']['topK'],9)
 def test_resume_accepts_concurrency_and_inactive_rcs_budget(self):
  rid=self.add('Question','failed')
  q.rpc(e,'settings.save',{'evidenceConcurrency':7,'rcsCandidateK':80})
  new=q.rpc(e,'resume',{'threadId':self.t['id'],'runId':rid})['id']
  snapshot=q.read(q.runpath(e,new)/'input.json')
  self.assertEqual(snapshot['resumeFrom'],rid);self.assertEqual(snapshot['config']['evidenceConcurrency'],7)

 def test_resume_uses_semantic_models_and_preserves_legacy_memo_aliases(self):
  p={'id':'original','model':'fixture','baseUrl':'https://example.invalid/v1','apiKey':'old','timeout':60,'visionModels':['fixture','other']}
  real_signature=lambda p:q.chunks.digest(q.llm_provider.semantic_fields(p))
  with patch.object(q,'profile_signature',side_effect=real_signature),patch.object(q,'models',return_value=(p,p)),patch.object(q,'evidence_model',return_value=p):
   rid=self.add('Question','failed');path=q.runpath(e,rid);snapshot=q.read(path/'input.json')
   old=q.legacy_profile_signature(p)
   snapshot['config']['answerProfile']='original'
   for role in ('planner','answer','evidence'):snapshot[role+'Signature']=old
   e.write_json(path/'input.json',snapshot)
   # Exact old credentials permit upgrade; thereafter credential/ID changes are harmless.
   new=q.rpc(e,'resume',{'threadId':self.t['id'],'runId':rid})['id']
   migrated=q.read(q.runpath(e,new)/'input.json')
   self.assertIn(old,migrated['profileAliases'][real_signature(p)])
   j=q.read(q.runpath(e,new)/'job.json');j['state']='failed';e.write_json(q.runpath(e,new)/'job.json',j)
   changed={**p,'id':'copy','apiKey':'rotated','timeout':300,'visionModels':['third','fixture']}
   with patch.object(q,'models',return_value=(changed,changed)),patch.object(q,'evidence_model',return_value=changed):
    resumed=q.rpc(e,'resume',{'threadId':self.t['id'],'runId':new})['id']
    self.assertIn(old,q.read(q.runpath(e,resumed)/'input.json')['profileAliases'][real_signature(p)])

 def test_parallel_threads_have_independent_status_cancel_and_retry(self):
  failed=self.add('Retry later','failed');second=q.rpc(e,'new',{});third=q.rpc(e,'new',{})
  with patch.object(q,'job',side_effect=REAL_JOB),patch.object(e,'process_alive',return_value=True):
   one=q.rpc(e,'start',{'threadId':self.t['id'],'question':'Question one'})['id']
   two=q.rpc(e,'start',{'threadId':second['id'],'question':'Question two'})['id']
   self.assertEqual({j['id'] for j in q.rpc(e,'statuses',{})},{one,two})
   # Other conversations remain manageable, even while two requests are live.
   copied=q.rpc(e,'copy',{'threadId':third['id']})
   q.rpc(e,'delete_many',{'threadIds':[third['id'],copied['id']]})
   with self.assertRaisesRegex(ValueError,'此对话正在生成'):q.rpc(e,'start',{'threadId':second['id'],'question':'Duplicate'})
   with self.assertRaisesRegex(ValueError,'此对话正在生成'):q.rpc(e,'regenerate',{'threadId':self.t['id'],'runId':failed})
   self.assertEqual(q.rpc(e,'cancel',{'runId':one})['state'],'stopping')
   self.assertFalse((q.runpath(e,two)/'cancel').exists())
   self.assertEqual(q.rpc(e,'status',{'runId':two})['state'],'queued')
   j=q.read(q.runpath(e,one)/'job.json');j['state']='failed';e.write_json(q.runpath(e,one)/'job.json',j)
   replacement=q.rpc(e,'regenerate',{'threadId':self.t['id'],'runId':one})['id']
   self.assertEqual({j['id'] for j in q.rpc(e,'statuses',{})},{replacement,two})
   self.assertEqual(q.thread(e,second['id'])['runIds'],[two])
   self.assertEqual(q.read(q.runpath(e,replacement)/'input.json')['history'][0]['question'],'Retry later')
if __name__=='__main__':unittest.main()
