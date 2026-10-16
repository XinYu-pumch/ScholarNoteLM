"""Mini-review QA contracts and round boundaries; no external model requests."""
import asyncio,copy,json,sqlite3,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,storage,qa_service as q,qa_mini_review as mini,qa_protocol,vector_chunks as chunks
from test_evidence_resources import PNG
import evidence_resources

class MiniReviewTests(unittest.TestCase):
 def test_missing_routing_id_completes_without_another_model_call(self):
  self.omit_unit_id=True
  job,_,path=self.execute()
  self.assertEqual(job['state'],'done',job.get('error'))
  self.assertFalse(list(path.glob('*修复问答格式*')))
  self.assertEqual(job['citationValidation']['problems'],[])
 def test_unrepairable_output_keeps_diagnostics_and_shows_friendly_error(self):
  self.output=[{'type':'markdown','text':'Unsupported claim [E999].'}]
  job,_,path=self.execute()
  self.assertEqual(job['state'],'failed')
  self.assertIn('回答格式需要修复',job['error'])
  self.assertNotIn('E999',job['error'])
  self.assertEqual(job['formatRepair']['state'],'failed')
  self.assertTrue(job['formatRepair']['reason'])
  self.assertTrue(list(path.glob('*修复问答格式.prompt.json.gz')))
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp')
  e.ROOT,e.PROJECT=Path(self.tmp.name),'mini';self.project=storage.project_dir(e.ROOT,e.PROJECT)
  self.rows=self.make_rows('A measured effect in mice.\n\n# Methods\n\nA different condition had no effect.\n\nFurther limitations.')
  self.route='research';self.context=[];self.history_requests=[];self.no_queries=False;self.partial_coverage=False;self.extra_history=[];self.extra_requested=False;self.calls=[];self.searches=[];self.full_calls=[];self.select=True;self.enough=True;self.vision=False;self.output=None;self.invalid_once=False;self.fail_answer=False;self.new_queries=True
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def make_rows(self,text):
  segments=chunks.split(text);objects=evidence_resources.extract(self.project,'123','v1',text,segments,e.atomic)
  return [{'id':'chunk-'+str(i),'text':s['text'],'metadata':{'pmid':'123','title':'Study','sourceKind':'fulltext','documentVersion':'v1','sourcePath':'markdown/123.md',**{k:v for k,v in s.items() if k not in ('text','accepted','reason')}},'resources':[o for o in objects if i in o['chunkIndices']]} for i,s in enumerate(segments)]
 def execute(self,cfg=None,resume=None):
  cfg=q.config(e,{'topK':1,'minRounds':1,'maxRounds':3,**(cfg or {})});rid=uuid.uuid4().hex;path=q.runpath(e,rid)
  snapshot={'id':rid,'policy':q.POLICY,'config':cfg,'mode':'topic','question':'What is the effect?','history':self.context,'pmids':None,'sourceSignature':'s','embeddingFingerprint':'v','plannerSignature':getattr(self,'signature','m'),'answerSignature':getattr(self,'signature','m'),'evidenceSignature':getattr(self,'signature','m'),'retrievalConfig':{'method':'api'}}
  if resume:snapshot['resumeFrom']=resume
  e.write_json(path/'input.json',snapshot);e.write_json(path/'job.json',{'id':rid,'question':snapshot['question'],'answerModel':'fixture','events':[],'round':0,'answer':'','state':'queued'})
  profile={'model':'fixture','visionModels':['fixture'] if self.vision else []}
  async def chat(profile,messages,cancelled,progress,on_text,on_reasoning=None):
   system=messages[0]['content'];content=messages[-1]['content'];payload=json.loads(content[0]['text'] if isinstance(content,list) else content)
   self.calls.append((system,payload,content))
   if '将用户问题拆解' in system:
    value={'route':self.route,'historyRequests':self.history_requests,'aspects':['effect'],'queries':[] if self.no_queries else [{'query':'What effect was measured in mice?','purpose':'effect'},{'query':'What effect was measured in mice?','purpose':'duplicate'}]}
   elif 'route=chat' in system or '仅按用户要求改写 sourceAnswers' in system:
    on_text('你好，请告诉我你想了解的问题。');return '你好，请告诉我你想了解的问题。'
   elif '逐要点说明支持' in system:
    value={'enough':self.enough,'coverage':[{'aspect':'effect','status':'supported' if self.enough and not self.partial_coverage else 'partial','evidenceIds':['E1'],'gap':'' if self.enough else 'Conditions unclear'}],
           'queries':[{'query':'Independent counterevidence in round '+str(payload['round']+1),'purpose':'conditions'}] if self.new_queries else [],'reason':'Evidence assessment'}
    if self.extra_history and not self.extra_requested:
     self.extra_requested=True;value.update(enough=False,queries=[],historyRequests=self.extra_history)
   else:
    if self.fail_answer:raise ValueError('Simulated provider failure')
    bundle=payload['materialBundle'];self.last_bundle=bundle
    blocks=self.output or [{'type':'markdown','text':'A measured effect [E1] [E2]. Another result [E1].' if len(bundle['evidencePool'])>1 else 'A measured effect [E1].'}]
    if self.invalid_once and '只修复输出结构' not in system:blocks=[{'type':'markdown','text':'Unknown [E999].'}]
    value={'unit_id':'answer','sections':[{'node_id':'answer','title':snapshot['question'],'blocks':blocks}]}
    if getattr(self,'omit_unit_id',False):value.pop('unit_id')
   text=json.dumps(value,ensure_ascii=False);on_text(text);return text
  owner=self
  class Retriever:
   def __init__(self,*args):owner.retriever_args=args
   def retrieve(self,query,candidates,k):
    owner.searches.append((query,candidates,k));return [{**r,'retrievalScore':.9} for r in owner.rows[:getattr(owner,'recall_count',1)]]
  papers=[{'pmid':'123','title':'Study','sourceKind':'fulltext'}]
  with patch.object(q,'chat',side_effect=chat),patch.object(q,'current_signature',return_value='s'),patch.object(q,'profile_signature',return_value=getattr(self,'signature','m')),patch.object(q,'models',return_value=(profile,profile)),patch.object(q,'evidence_model',return_value=profile),patch.object(q.retrieval_settings,'fingerprint',return_value='v'),patch.object(q,'corpus',return_value=([self.rows[0]],{},papers,{'papers':1,'searchablePapers':1})),patch.object(mini.retrieval,'Retriever',Retriever),patch.object(mini.retrieval,'ready',return_value=True):
   asyncio.run(q.run(e,rid))
  return q.read(path/'job.json'),q.read(path/'evidence.json',[]),path
 def test_disabled_fulltext_skips_selection_loading_and_expansion(self):
  job,ev,path=self.execute({'minRounds':2})
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],2)
  self.assertEqual(len(ev),1);self.assertFalse(self.full_calls)
  self.assertFalse(any('选择为解答 question' in system for system,_,_ in self.calls))
  for _,payload,_ in self.calls:
   if 'materialBundle' in payload:
    self.assertEqual(len(payload['materialBundle']['evidencePool']),1);self.assertNotIn('documents',payload)
  self.assertFalse((path/'documents.json').exists())
 def test_lower_bound_forces_new_queries_despite_sufficient_evidence(self):
  job,ev,_=self.execute({'minRounds':3,'maxRounds':4,'maxSteps':1,'fulltextEnabled':True})
  self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],3);self.assertEqual(len(self.searches),3)
  self.assertEqual(len({r[0] for r in self.searches}),3);self.assertFalse(self.full_calls);self.assertEqual(len(ev),1)
 def test_upper_bound_produces_limited_answer_when_not_sufficient(self):
  self.enough=False;self.select=False
  job,ev,_=self.execute({'maxRounds':2});self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['round'],2)
  self.assertIn('最多',job['stopReason']);self.assertEqual(len(ev),1);self.assertFalse(self.full_calls)
 def test_no_hard_fulltext_trigger(self):
  self.select=False;job,ev,_=self.execute({'fulltextEnabled':True});self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(len(ev),1);self.assertFalse(self.full_calls)
 def test_empty_followup_does_not_fabricate_minimum_rounds(self):
  self.new_queries=False
  job,_,_=self.execute({'minRounds':2});self.assertEqual(job['state'],'failed');self.assertEqual(job['round'],1)
  self.assertIn('未虚增',job['error'])
 def test_resource_citations_tables_images_and_source_rpc(self):
  e.atomic(self.project/'markdown/assets/123/figure.png',PNG)
  self.rows=self.make_rows('Evidence context.\n\n![](assets/123/figure.png)\n\n| Group | Result |\n|---|---|\n| A | 42 |\n\nCaption.');self.vision=True
  self.output=[{'type':'markdown','text':'See 图 {{ref:R1}} and {{ref:T1}} [E1] [R1].'},
    {'type':'resource','resource_id':'R1'},
    {'type':'table','table_id':'T1','title':'Comparison','columns':['Group','Result'],'rows':[['A','42 [R2]']],'notes':'Mice.'}]
  job,ev,path=self.execute();self.assertEqual(job['state'],'done',job.get('error'))
  self.assertEqual([b['type'] for b in job['answerBlocks']],['markdown','resource','table']);self.assertNotIn('图 图',job['answer'])
  self.assertNotIn('{{ref:',job['answer']);self.assertEqual(job['answerBlocks'][1]['dataUrl'],'data:image/png;base64,'+__import__('base64').b64encode(PNG).decode())
  answer_call=self.calls[-1][2];self.assertEqual(sum(p['type']=='image_url' for p in answer_call),1)
  for call in self.calls:
   if 'materialBundle' in call[1]:self.assertEqual(len(call[1]['materialBundle']['resources']),2)
  public=q.public_job(e,job['id']);self.assertIn('R1',[r['eid'] for r in public['evidence']]);self.assertIn('R2',[r['eid'] for r in public['evidence']])
  obj=q.rpc(e,'evidence',{'runId':job['id'],'evidenceId':'R2'});self.assertIn('42',obj['text']);self.assertEqual(obj['metadata']['pmid'],'123')
  tid=uuid.uuid4().hex;e.write_json(q.threadpath(e,tid),{'id':tid,'name':'Test','runIds':[job['id']]})
  exported=q.rpc(e,'export',{'threadId':tid});self.assertIn('![图 1]',exported['content']);self.assertTrue(list((q.root(e)/'exports'/f'{tid}-assets').glob('*.png')))
 def test_unseen_image_cannot_be_inserted(self):
  e.atomic(self.project/'markdown/assets/123/figure.png',PNG)
  self.rows=self.make_rows('Context.\n\n![](assets/123/figure.png)\n\nCaption.')
  self.output=[{'type':'resource','resource_id':'R1'}]
  job,_,_=self.execute();self.assertEqual(job['state'],'failed');self.assertIn('回答格式需要修复',job['error'])
  self.assertIn('图像输入',job['formatRepair']['reason']);self.assertEqual(job['formatRepair']['state'],'failed')
 def test_format_repair_uses_same_complete_pool(self):
  self.invalid_once=True;job,_,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'))
  writing=[p for s,p,_ in self.calls if '小综述，按 materialBundle' in s];self.assertEqual(len(writing),2)
  self.assertEqual(writing[0]['materialBundle'],writing[1]['materialBundle']);self.assertIn('E999',writing[1]['invalidOutput'])
 def test_long_output_is_not_truncated(self):
  self.output=[{'type':'markdown','text':'Long supported statement. '*90000+' [E1]'}]
  job,_,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'));self.assertGreater(len(job['answer']),2_000_000)
 def test_resume_reuses_successful_planning(self):
  self.fail_answer=True;job,_,_=self.execute({'fulltextEnabled':True});self.assertEqual(job['state'],'failed')
  self.fail_answer=False;self.calls=[];done,_,_=self.execute({'fulltextEnabled':True},resume=job['id']);self.assertEqual(done['state'],'done',done.get('error'))
  self.assertEqual(len(self.calls),1);self.assertIn('小综述，按 materialBundle',self.calls[0][0])

 def test_old_profile_hash_reuses_successful_calls_after_upgrade(self):
  self.signature=q.legacy_profile_signature({'model':'fixture','visionModels':[]})
  self.fail_answer=True;job,_,_=self.execute();self.assertEqual(job['state'],'failed')
  self.signature='m';self.fail_answer=False;self.calls=[]
  done,_,_=self.execute(resume=job['id']);self.assertEqual(done['state'],'done',done.get('error'))
  self.assertEqual(len(self.calls),1);self.assertIn('小综述，按 materialBundle',self.calls[0][0])


if __name__=='__main__':unittest.main()
