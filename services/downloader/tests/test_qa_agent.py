import asyncio,json,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,qa_service as q,qa_evidence as cards,storage

class AgentTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp')
  e.ROOT,e.PROJECT=Path(self.tmp.name),'agent';storage.project_dir(e.ROOT,e.PROJECT)
  self.rows=[{'id':str(i),'text':f'Source {i}. No effect in mice.', 'metadata':{'pmid':str(100+i),'title':f'Study {i}','sourceKind':'pubmed_abstract','documentVersion':str(i),'sectionPath':['Results']}} for i in range(5)]
  self.papers=[{'pmid':r['metadata']['pmid'],'title':r['metadata']['title'],'sourceKind':'pubmed_abstract'} for r in self.rows]
  self.vision=False;self.image_inputs=[];self.requests=[];self.fail_id=None;self.invalid_id=None;self.only_tools=False;self.active=0;self.peak=0
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def execute(self,config=None,mode='topic',resume=None,question='Does it help?'):
  cfg=q.config(e,{'topK':2,'rcsCandidateK':4,'evidenceConcurrency':2,**(config or {})});rid=uuid.uuid4().hex;path=q.runpath(e,rid)
  snapshot={'id':rid,'config':cfg,'mode':mode,'question':question,'history':[],'pmids':None,'sourceSignature':'s','embeddingFingerprint':'v','plannerSignature':'m','answerSignature':'m','evidenceSignature':'m'}
  if resume:snapshot['resumeFrom']=resume
  e.write_json(path/'input.json',snapshot);e.write_json(path/'job.json',{'id':rid,'events':[],'round':0,'answer':'','state':'queued'})
  async def model(profile,messages,cancelled,progress,on_text,on_reasoning=None):
   system=messages[0]['content'];content=messages[-1]['content']
   if isinstance(content,list):self.image_inputs.append((profile['model'],content));content=content[0]['text']
   payload=json.loads(content);self.requests.append((profile['model'],system,payload))
   if '"aspects"' in system:
    value={'aspects':['effect'],'queries':[],'tools':[{'tool':'gather_evidence','query':'effect evidence','purpose':'test'}]}
   elif '"score"' in system:
    source=payload['evidence'];i=int(source['pmid'])-100;self.active+=1;self.peak=max(self.peak,self.active)
    try:
     await asyncio.sleep(.005)
     if i==self.fail_id:raise ValueError('模型请求失败（HTTP 503）')
     value={'score':i+1,'summary':'No effect','context':'mice','aspect':'effect','relation':'counter','quotes':[source['text']]}
     if i==self.invalid_id:value['quotes']=['Invented result.']
    finally:self.active-=1
   elif '"cards"' in system:
    value={'cards':[{'eid':r['eid'],'summary':'No effect','context':'mice','aspect':'effect','relation':'counter','quotes':[r['text']]} for r in payload['evidence']]}
   elif '"coverage"' in system:
    if self.only_tools and payload['agentStep']==1:value={'enough':False,'coverage':[],'queries':[],'tools':[{'tool':'find_in_sources','text':'Source 4.'}],'reason':'Locate counterevidence outside first recall'}
    elif self.only_tools and payload['agentStep']==2:value={'enough':False,'coverage':[],'queries':[],'tools':[{'tool':'generate_answer','reason':'Enough'}],'reason':'Enough'}
    else:value={'enough':True,'coverage':[],'queries':[],'tools':[],'reason':'Enough'}
   else:
    if self.fail_id=='answer':raise ValueError('模型请求失败（HTTP 503）')
    value='Limited answer '+''.join('['+r['eid']+']' for r in payload['evidence'])
   text=value if isinstance(value,str) else json.dumps(value);on_text(text);return text
  def rank(tools,queries,limit):return [{'query':query,'hits':[{'record':r,'score':1-i*.1} for i,r in enumerate(self.rows[:limit])]} for query in queries]
  with patch.object(q,'chat',side_effect=model),patch.object(q,'current_signature',return_value='s'),patch.object(q,'profile_signature',return_value='m'),patch.object(q,'models',return_value=({'model':'controller','visionModels':['controller'] if self.vision else []},{'model':'answer','visionModels':['answer'] if self.vision else []})),patch.object(q,'evidence_model',return_value={'model':'reader'}),patch.object(q.retrieval_settings,'fingerprint',return_value='v'),patch.object(q,'corpus',return_value=(self.rows,{},self.papers,{'papers':len(self.papers),'searchablePapers':len(self.papers)})),patch.object(q.EvidenceTools,'rank',rank):asyncio.run(q.run(e,rid))
  return q.read(path/'job.json'),q.read(path/'evidence.json')
 def test_complete_answer_receives_full_tables_and_images(self):
  from test_evidence_resources import PNG
  import evidence_resources as resources,vector_chunks as chunks
  project=storage.project_dir(e.ROOT,e.PROJECT)
  e.atomic(project/'markdown/assets/100/figure.png',PNG)
  source='Context.\n\n![](assets/100/figure.png)\n\n| Gene | Value |\n|---|---|\n| A | 42 |\n\nCaption.'
  objects=resources.extract(project,'100','v',source,chunks.split(source),e.atomic)
  self.rows[0]['resources']=objects;self.vision=True
  job,ev=self.execute();self.assertEqual(job['state'],'done',job.get('error'))
  self.assertEqual(next(r for r in ev if r['id']=='0')['resources'],objects)
  answer=next(payload for model,_,payload in self.requests if model=='answer')
  self.assertEqual(answer['associatedResources'],objects)
  images=next(parts for model,parts in self.image_inputs if model=='answer')
  self.assertEqual(sum(part['type']=='image_url' for part in images),1)
  self.assertEqual(images[-1]['image_url']['url'],'data:image/png;base64,'+__import__('base64').b64encode(PNG).decode())
  self.vision=False;self.requests=[];self.image_inputs=[]
  job,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'));self.assertFalse(self.image_inputs)
  self.assertTrue(any('未提供图像输入' in system for model,system,_ in self.requests if model=='answer'))
 def test_default_off_calls_no_evidence_model_and_retains_exactly_b(self):
  j,ev=self.execute();self.assertEqual(j['state'],'done',j.get('error'));self.assertEqual(len(ev),2)
  self.assertEqual({p for p,_,_ in self.requests},{'controller','answer'})
  self.assertTrue(all('score' not in r['card'] for r in ev));self.assertEqual(j['round'],1)
 def test_rcs_a_candidates_are_scored_then_best_b_including_counterevidence(self):
  j,ev=self.execute({'rcsEnabled':True});self.assertEqual(j['state'],'done',j.get('error'))
  self.assertEqual({r['id'] for r in ev},{'2','3'});self.assertEqual(j['readingCoverage']['assessedChunks'],4)
  self.assertEqual(len([r for r in self.requests if r[0]=='reader']),4);self.assertEqual(self.peak,2)
  self.assertTrue(all(r['card']['relation']=='counter' for r in ev))
  decisions=[p for _,s,p in self.requests if '"coverage"' in s];self.assertTrue(decisions[0]['evidence'][0]['text'])
 def test_bad_quote_is_unassessed_not_zero_and_never_used_as_summary(self):
  self.invalid_id=3;j,ev=self.execute({'rcsEnabled':True,'topK':4})
  self.assertEqual(j['state'],'done',j.get('error'));self.assertTrue(j['qualityWarnings'])
  bad=next(r for r in ev if r['id']=='3');self.assertEqual(bad['card']['status'],'unassessed');self.assertNotIn('score',bad['card']);self.assertNotIn('Invented',json.dumps(ev))
 def test_cards_cache_is_bound_to_question_and_source_not_query(self):
  self.execute({'rcsEnabled':True});self.requests=[];j,_=self.execute({'rcsEnabled':True})
  self.assertEqual(j['state'],'done');self.assertFalse(any(r[0]=='reader' for r in self.requests))
  self.requests=[];self.execute({'rcsEnabled':True},question='Different conditions?');self.assertEqual(len([r for r in self.requests if r[0]=='reader']),4)
  self.requests=[];self.rows[0]['text']='Changed source.';self.execute({'rcsEnabled':True});self.assertEqual(len([r for r in self.requests if r[0]=='reader']),1)
 def test_retired_paper_worker_rejects_before_model_calls(self):
  j,_=self.execute(mode='paper');self.assertEqual(j['state'],'failed');self.assertIn('已停用',j['error']);self.assertFalse(self.requests)
 def test_overview_reads_every_prepared_paper_without_embedding_or_scores(self):
  self.papers.append({'pmid':'999','title':'Unavailable','sourceKind':'pending_fulltext'})
  with patch.object(q.EvidenceTools,'search',side_effect=AssertionError('must not shortlist')):
   j,ev=self.execute(mode='overview')
  self.assertEqual(j['state'],'done',j.get('error'));self.assertEqual(len(ev),5)
  self.assertEqual(j['round'],0);self.assertEqual(j['readingCoverage']['examinedPapers'],5)
  states={p['pmid']:p['status'] for p in j['readingCoverage']['paperRead']};self.assertEqual(states['999'],'unavailable')
  self.assertTrue(all('score' not in r['card'] for r in ev));self.assertEqual(len([r for r in self.requests if r[0]=='reader']),5)
 def test_tools_can_read_beyond_recall_and_explicitly_finish_within_step_budget(self):
  self.only_tools=True;j,ev=self.execute({'maxRounds':1})
  self.assertEqual(j['state'],'done',j.get('error'));self.assertEqual(j['round'],1);self.assertEqual(j['agentStep'],3)
  self.assertIn('4',{r['id'] for r in ev});self.assertEqual(j['readingCoverage']['poolPapers'],3)
 def test_partial_rcs_failure_preserves_successful_cards_resume_only_failed_call(self):
  self.fail_id=2;j,ev=self.execute({'rcsEnabled':True});self.assertEqual(j['state'],'failed');self.assertFalse(ev)
  self.vision=False;self.image_inputs=[];self.requests=[];self.fail_id=None;done,ev=self.execute({'rcsEnabled':True},resume=j['id'])
  self.assertEqual(done['state'],'done',done.get('error'));self.assertEqual(len(ev),2)
  self.assertEqual(len([r for r in self.requests if r[0]=='reader']),1);self.assertFalse(any('"aspects"' in s for _,s,_ in self.requests))
 def test_answer_failure_resume_reuses_controller_and_scan_checkpoints(self):
  self.fail_id='answer';j,_=self.execute(mode='overview');self.assertEqual(j['state'],'failed')
  self.vision=False;self.image_inputs=[];self.requests=[];self.fail_id=None;done,_=self.execute(mode='overview',resume=j['id'])
  self.assertEqual(done['state'],'done',done.get('error'));self.assertEqual([x[0] for x in self.requests],['answer'])
 def test_rcs_config_and_public_tool_contracts(self):
  self.assertFalse(q.config(e)['rcsEnabled'])
  for changes in ({'rcsEnabled':'false'},{'rcsEnabled':True,'topK':25,'rcsCandidateK':24},{'evidenceConcurrency':0},{'maxSteps':False}):
   with self.assertRaises(ValueError):q.config(e,changes)
  self.assertEqual(q.validate_tool({'tool':'read_context','pmid':'123'})['tool'],'section')
  self.assertEqual(q.validate_tool({'tool':'read_context','evidenceId':'E1'})['tool'],'neighbors')
  with self.assertRaises(q.ToolInputError):q.validate_tool({'tool':'gather_evidence'})
  with self.assertRaises(q.ToolInputError):q.validate_tool({'tool':'find_in_sources','text':'x','url':'https://example.com'})
 def test_zero_or_irrelevant_cards_do_not_get_filled_with_unrelated_candidates(self):
  rows=[{'card':{'status':'assessed','score':9,'relation':'irrelevant'},'similarity':1}, {'card':{'status':'assessed','score':0,'relation':'direct'},'similarity':.9}]
  self.assertFalse(cards.select_candidates(rows,8))
  with self.assertRaises(ValueError):cards.validate_card({'score':True,'relation':'irrelevant'},self.rows[0],q.quote_match)
 def test_missing_vector_cache_preserves_note_and_finishes_without_model_scoring(self):
  def empty(tools,queries):return [{'query':query,'hits':[],'note':'当前范围没有有效缓存向量'} for query in queries]
  with patch.object(q.EvidenceTools,'search',empty):j,ev=self.execute()
  self.assertEqual(j['state'],'done',j.get('error'));self.assertFalse(ev)
  self.assertEqual(j['citationValidation']['status'],'no_evidence')
  self.assertIn('有效缓存',next(x for x in j['events'] if x['type']=='search')['note'])
 def test_resume_rejects_changed_source_or_settings_before_spawning(self):
  cfg=q.config(e);e.write_json(e.ROOT/'config/qa.json',cfg)
  tid=uuid.uuid4().hex;rid=uuid.uuid4().hex
  e.write_json(q.threadpath(e,tid),{'id':tid,'name':'Test','runIds':[rid]})
  prior={'question':'Question','config':cfg,'pmids':None,'mode':'topic','sourceSignature':'old',
         'embeddingFingerprint':'v','plannerSignature':'m','answerSignature':'m','evidenceSignature':'m','policy':q.POLICY,'history':[]}
  e.write_json(q.runpath(e,rid)/'input.json',prior)
  e.write_json(q.runpath(e,rid)/'job.json',{'id':rid,'question':'Question','state':'failed'})
  with patch.object(q,'models',return_value=({'model':'mock'},{'model':'mock'})),patch.object(q,'current_signature',return_value='changed'),patch.object(q,'profile_signature',return_value='m'),patch.object(q.retrieval_settings,'fingerprint',return_value='v'),patch.object(q,'corpus',return_value=([],{},self.papers,{})),patch.object(q.subprocess,'Popen',side_effect=AssertionError('must not spawn')):
   with self.assertRaisesRegex(ValueError,'无法继续检查点'):q.start(e,{'threadId':tid,'question':'Question','resumeFrom':rid})
   prior['sourceSignature']='changed';prior['config']={**cfg,'rcsEnabled':True};e.write_json(q.runpath(e,rid)/'input.json',prior)
   with self.assertRaisesRegex(ValueError,'无法继续检查点'):q.start(e,{'threadId':tid,'question':'Question','resumeFrom':rid})

if __name__=='__main__':unittest.main()
