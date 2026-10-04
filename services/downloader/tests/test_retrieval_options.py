import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,retrieval_settings as s,review_writing as w,vector_service as v,embedding_limits as limits,review_retrieval as r

class RetrievalOptionsTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT=Path(self.tmp.name)
 def tearDown(self):e.ROOT=self.old;self.tmp.cleanup()
 def test_api_selection_requires_exact_saved_verified_configuration(self):
  cfg=v.validated(e,{'baseUrl':'https://example.test/v1','model':'bge','apiKey':'secret'})
  e.write_json(e.ROOT/'config/embedding.json',{'profiles':[{**cfg,'id':'legacy','name':'默认配置'}],'activeProfile':'legacy'})
  with self.assertRaisesRegex(ValueError,'测试'):v.rpc(e,'profile.activate',{'id':'legacy'})
  s.mark_verified(e,cfg,3);self.assertTrue(s.verified(e.ROOT));self.assertEqual(s.read(e.ROOT)['method'],'api')
  for key,value in [('apiKey','newsecret'),('model','different'),('baseUrl','https://example.test/v2'),('modelRevision','v2')]:
   self.assertFalse(s.verified(e.ROOT,{**cfg,key:value}),key)
  self.assertTrue(s.verified(e.ROOT,{**cfg,'timeout':100}))
  self.assertNotIn('secret',(e.ROOT/'config/embedding-verification.json').read_text())
 def test_limiter_shared_and_reconciles_actual_usage(self):
  cfg={**v.DEFAULTS,'baseUrl':'https://example.test/v1'};a=limits.Limiter(e.ROOT,cfg);b=limits.Limiter(e.ROOT,cfg)
  ident=a.acquire(123);a.reconcile(ident,{'prompt_tokens':12})
  with b.db() as c:self.assertEqual(c.execute('SELECT tokens FROM requests').fetchone()[0],12)
  a.cooldown(2)
  with b.db() as c:self.assertGreater(c.execute('SELECT until FROM gates').fetchone()[0],time.time()+1)
  with self.assertRaisesRegex(ValueError,'TPM'):a.acquire(120001)
 def test_wait_can_cancel_before_any_request(self):
  cfg={**v.DEFAULTS,'baseUrl':'https://example.test/v1'}
  def cancel():raise ValueError('cancelled')
  with self.assertRaisesRegex(ValueError,'cancelled'):limits.Limiter(e.ROOT,cfg,cancel).acquire(10)
 def test_429_retry_after_and_complete_batch_packing(self):
  import httpx
  calls=[];codes=iter([429,200,200])
  def post(url,headers,payload,timeout,check):
   calls.append(payload['input']);code=next(codes)
   return httpx.Response(code,headers={'Retry-After':'2'},json={'data':[{'index':i,'embedding':[1,2]} for i,_ in enumerate(payload['input'])]})
  cfg={**v.DEFAULTS,'baseUrl':'https://example.test/v1','batchSize':64,'rpm':60000,'tpm':35}
  with patch.object(limits,'post',side_effect=post),patch.object(limits.Limiter,'acquire',return_value='test'),patch.object(limits.Limiter,'cooldown') as cool,patch.object(limits,'wait') as wait:
   result=v.embed(['abcdefghijklmnop','qrstuvwxyzABCDEF'],cfg,root=e.ROOT)
  self.assertEqual(result,[[1,2],[1,2]]);self.assertEqual(calls,[['abcdefghijklmnop'],['abcdefghijklmnop'],['qrstuvwxyzABCDEF']]);cool.assert_called_with(2);wait.assert_called_with(2,unittest.mock.ANY)
 def test_api_retrieval_uses_exact_topk(self):
  class Recall:
   def __init__(self,*args):pass
   def recall(self,q,k):seen.append((q,k));return [(i,float(10-i)) for i in range(min(k,10))]
  records=[{'id':str(i),'text':'x','metadata':{}} for i in range(10)];seen=[]
  with patch.object(r,'APIRecall',Recall):
   retriever=r.Retriever(e.ROOT,e.ROOT,records,lambda:None,lambda p:None,{'method':'api','reranker':'none'})
   self.assertEqual(len(retriever.retrieve('中文原始标题',50,7)),7)
  self.assertEqual(seen,[('中文原始标题',7)])
 def test_api_recall_sends_only_body_and_ignores_old_profile_cache(self):
  try:import numpy as np
  except ImportError:self.skipTest('Run API recall tests in runtimes/retrieval (requires numpy)')
  import struct,vector_chunks as chunks
  from types import SimpleNamespace
  env=SimpleNamespace(ROOT=e.ROOT,PROJECT='test')
  cfg={**v.DEFAULTS,'baseUrl':'https://example.test/v1','model':'test'}
  records=[{'id':'body','text':'PSA activates TLR2.','metadata':{'pmid':'123','title':'Unrelated title','sectionPath':['A heading']}}]
  with patch.object(chunks,'TEMPLATE','title-section-body-v1'):old_profile=v.profile(cfg)
  with chunks.connect(env) as db:
   db.execute('INSERT INTO embeddings VALUES(?,?,?,?)',(old_profile,chunks.digest(records[0]['text']),2,struct.pack('<ff',0.,1.)))
  with patch.object(v,'config',return_value=cfg),patch.object(s,'verified',return_value=True),patch('corpus_files.current',return_value={'123'}),patch('artifact_state.epoch',return_value=0),patch.object(v,'embed',return_value=[[1.,0.]]) as embed:
   recall=r.APIRecall(env,records,{},lambda:None,lambda p:None)
   embed.assert_called_once();self.assertEqual(embed.call_args.args[0],['PSA activates TLR2.'])
   np.testing.assert_array_equal(recall.matrix,np.asarray([[1.,0.]],dtype='float32'))
if __name__=='__main__':unittest.main()
