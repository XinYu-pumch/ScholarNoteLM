"""Provider isolation, Jina protocol, cache compatibility and proxy routing."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,vector_service as v,embedding_profiles as profiles,embedding_providers as providers
import retrieval_settings,vector_chunks

class ProviderTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT=Path(self.tmp.name)
 def tearDown(self):e.ROOT=self.old;self.tmp.cleanup()
 def test_presets_are_keyless_and_provider_limits_do_not_leak(self):
  presets=providers.presets();self.assertTrue(all(not p['apiKey'] for p in presets))
  saved=[]
  for preset in presets:
   saved.append(profiles.save(e,{**preset,'id':'','apiKey':'fixture-'+preset['name']}))
  a,b=[profiles.get(e,pid) for pid in saved]
  self.assertEqual([a[k] for k in ('batchSize','concurrency','rpm','tpm')],[32,4,1800,450000])
  self.assertEqual([b[k] for k in ('batchSize','concurrency','rpm','tpm')],[32,2,100,100000])
  before=v.profile(a);profiles.save(e,{'id':b['id'],'rpm':80,'tpm':90000,'batchSize':8,'concurrency':1})
  self.assertEqual(profiles.get(e,a['id']),a);self.assertEqual(v.profile(profiles.get(e,a['id'])),before)
  self.assertEqual(profiles.active(e)['id'],a['id'])
  self.assertNotIn('fixture-siliconflow',json.dumps(v.settings(e)))
  self.assertNotIn('fixture-jina',json.dumps(v.settings(e)))
 def test_existing_generic_signatures_are_unchanged(self):
  cfg={**v.DEFAULTS,'baseUrl':'https://api.siliconflow.cn/v1/embeddings','model':'Pro/BAAI/bge-m3','apiKey':'fixture'}
  self.assertEqual(v.profile(cfg),vector_chunks.digest([cfg['baseUrl'],cfg['model'],'',vector_chunks.TEMPLATE]))
  self.assertEqual(retrieval_settings.fingerprint(cfg),vector_chunks.digest([v.endpoint(cfg),cfg['model'],'','fixture']))
  jina={**cfg,'baseUrl':'https://api.jina.ai/v1/embeddings','model':'jina-embeddings-v3'}
  self.assertNotEqual(v.profile(jina),vector_chunks.digest([jina['baseUrl'],jina['model'],'',vector_chunks.TEMPLATE]))
  self.assertNotEqual(retrieval_settings.fingerprint(jina),vector_chunks.digest([v.endpoint(jina),jina['model'],'','fixture']))
 def test_jina_query_document_payload_and_batch_splits(self):
  import httpx
  cfg={**v.DEFAULTS,**providers.presets()[1],'batchSize':1,'rpm':1000000}
  def post(url,headers,payload,timeout,check):
   self.assertEqual(url,'https://api.jina.ai/v1/embeddings')
   self.assertEqual(payload['task'],'retrieval.query');self.assertEqual(payload['embedding_type'],'float')
   self.assertIs(payload['truncate'],False);self.assertNotIn('encoding_format',payload)
   return httpx.Response(200,json={'data':[{'index':0,'embedding':[1.,2.]}],'usage':{'total_tokens':2}})
  with patch('embedding_limits.post',side_effect=post) as send:
   self.assertEqual(v.embed(['first','second'],cfg,root=e.ROOT,purpose='query'),[[1.,2.],[1.,2.]])
   self.assertEqual(send.call_count,2)
  self.assertEqual(providers.payload(['paper'],cfg,'document')['task'],'retrieval.passage')
  cfg['baseUrl']='https://example.test/v1'
  self.assertEqual(providers.payload(['paper'],cfg,'query'),{'model':cfg['model'],'input':['paper'],'encoding_format':'float'})
 def test_jina_list_excludes_other_api_types_and_multivectors(self):
  rows=[{'id':'jina-ai/jina-embeddings-v5-text-nano','output_modalities':['embeddings'],'input_modalities':['text']},
        {'id':'jina-ai/jina-clip-v2','output_modalities':['embeddings'],'input_modalities':['text','image']},
        {'id':'jina-ai/jina-colbert-v2','output_modalities':['embeddings'],'input_modalities':['text']},
        {'id':'jina-ai/jina-reranker-v3','output_modalities':['text'],'input_modalities':['text']}]
  self.assertEqual(providers.model_ids(rows,providers.presets()[1]),['jina-clip-v2','jina-embeddings-v5-text-nano'])
 def test_proxy_respects_bypass_and_keeps_local_services_direct(self):
  with patch('urllib.request.getproxies',return_value={'https':'http://127.0.0.1:7890'}),patch('urllib.request.proxy_bypass',return_value=False):
   self.assertEqual(providers.system_proxy('https://api.jina.ai/v1/embeddings'),'http://127.0.0.1:7890')
   for host in ('localhost','127.0.0.1','[::1]'):self.assertIsNone(providers.system_proxy('http://'+host+':1234/v1'))
  with patch('urllib.request.proxy_bypass',return_value=True):self.assertIsNone(providers.system_proxy('https://api.jina.ai/v1/embeddings'))

if __name__=='__main__':unittest.main()
