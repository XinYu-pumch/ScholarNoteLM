"""QA guards use real source changes; remote models are never called."""
import asyncio,json,sys,tempfile,threading,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,qa_service as q,storage


class QAMaterialsTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp')
  e.ROOT,e.PROJECT=Path(self.tmp.name),'guard';self.base=storage.project_dir(e.ROOT,e.PROJECT)
  self.source=self.base/'pubmed/current.xml';self.write_source('Original')
  self.profile={'id':'fixture','model':'fixture','baseUrl':'http://localhost/v1'}
  self.calls=[];self.threads=[];self.main_thread=threading.get_ident()
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def write_source(self,title):
  e.atomic(self.source,f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>{title}</ArticleTitle><Abstract><AbstractText>Original evidence in mice.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
 def execute(self,mode='normal'):
  rid=uuid.uuid4().hex;path=q.runpath(e,rid);cfg=q.config(e)
  snapshot={'id':rid,'policy':q.POLICY,'config':cfg,'mode':'topic','question':'Hello','history':[],'pmids':None,
   'sourceSignature':q.current_signature(e),'embeddingFingerprint':q.retrieval_settings.fingerprint(q.vectors.config(e)),
   'plannerSignature':q.profile_signature(self.profile),'answerSignature':q.profile_signature(self.profile)}
  e.write_json(path/'input.json',snapshot);e.write_json(path/'job.json',{'id':rid,'events':[],'round':0,'answer':'','state':'queued'})
  original=q.current_signature
  def signature(engine):self.threads.append(threading.get_ident());return original(engine)
  async def chat(profile,messages,cancelled,progress,on_text,on_reasoning=None):
   self.calls.append(messages);before=len(self.threads)
   for _ in range(100):
    self.assertFalse(cancelled());await asyncio.sleep(0)
   self.assertEqual(len(self.threads),before,'Network callbacks scanned materials')
   plan='将用户问题拆解' in messages[0]['content']
   if not plan:
    if mode=='mutation':self.write_source('Changed while streaming')
    if mode=='config':
     self.profile['model']='changed';e.write_json(e.ROOT/'config/models.json',{'revision':1})
    if mode=='cancel':(path/'cancel').touch();cancelled()
   value=json.dumps({'route':'chat','aspects':[],'queries':[],'historyRequests':[]}) if plan else 'Complete answer'
   on_text(value);return value
  original_images=q.resources.with_images
  def images(*args,**kwargs):
   result=original_images(*args,**kwargs)
   if mode=='before_send':self.write_source('Changed during request assembly')
   return result
  original_save=e.write_json
  def save(file,data):
   original_save(file,data)
   # Change after response validation but before final publication.
   if mode=='before_publish' and Path(file).name=='completed-calls.json' and len(data)==2:self.write_source('Changed before publication')
  with patch.object(q,'current_signature',side_effect=signature),patch.object(q,'models',return_value=(self.profile,self.profile)),patch.object(q,'evidence_model',return_value=self.profile),patch.object(q,'chat',side_effect=chat),patch.object(q.resources,'with_images',side_effect=images),patch.object(e,'write_json',side_effect=save):
   asyncio.run(q.run(e,rid))
  return q.read(path/'job.json'),path
 def test_unchanged_inputs_checked_once_off_event_loop(self):
  job,_=self.execute();self.assertEqual(job['state'],'done',job.get('error'));self.assertEqual(job['answer'],'Complete answer')
  self.assertEqual(len(self.threads),1);self.assertNotIn(self.main_thread,self.threads);self.assertEqual(len(self.calls),2)
 def test_changes_during_streaming_block_answer(self):
  job,path=self.execute('mutation');self.assertEqual(job['state'],'failed');self.assertFalse(job['answer']);self.assertFalse(job.get('draft'))
  self.assertFalse(list(path.glob('*对话回复.response.txt*')));self.assertEqual(len(self.calls),2)
 def test_changes_before_send_prevent_request(self):
  job,_=self.execute('before_send');self.assertEqual(job['state'],'failed');self.assertEqual(self.calls,[]);self.assertFalse(job['answer'])
 def test_changes_before_final_publication_block_answer(self):
  job,_=self.execute('before_publish');self.assertEqual(job['state'],'failed');self.assertFalse(job['answer'])
 def test_model_config_change_invalidates_guard(self):
  job,_=self.execute('config');self.assertEqual(job['state'],'failed');self.assertIn('模型配置',job['error']);self.assertFalse(job['answer'])
 def test_cancellation_remains_immediate(self):
  job,_=self.execute('cancel');self.assertEqual(job['state'],'cancelled');self.assertFalse(job['answer']);self.assertEqual(len(self.threads),1)

if __name__=='__main__':unittest.main()
