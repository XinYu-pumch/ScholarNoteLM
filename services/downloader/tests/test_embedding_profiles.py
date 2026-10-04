import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,vector_service as v,embedding_profiles as p,retrieval_settings as r

class EmbeddingProfilesTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT=Path(self.tmp.name)
 def tearDown(self):e.ROOT=self.old;self.tmp.cleanup()
 def create(self,name='Alpha',model='embed-a',**extra):
  result=v.rpc(e,'settings.save',{'id':'','name':name,'baseUrl':'https://example.test/v1','model':model,'apiKey':'fixture-secret',**extra})
  return p.get(e,result['savedProfile'])
 def test_new_profiles_do_not_switch_active_or_inherit_keys(self):
  a=self.create();b=self.create('Beta','embed-b',apiKey='')
  self.assertEqual(v.config(e)['id'],a['id']);self.assertEqual(b['apiKey'],'')
  self.assertNotIn('fixture-secret',json.dumps(v.settings(e)));self.assertEqual(v.rpc(e,'profile.key',{'id':a['id']}),{'apiKey':'fixture-secret'})
  v.rpc(e,'settings.save',{'id':b['id'],'name':'Beta 2','apiKey':'other-secret'})
  self.assertEqual(p.get(e,a['id'])['apiKey'],'fixture-secret')
  v.rpc(e,'settings.save',{'id':b['id'],'clearKey':True});self.assertEqual(p.get(e,b['id'])['apiKey'],'')
 def test_verified_selection_can_switch_back_without_rebuilding_or_retesting(self):
  a=self.create();b=self.create('Beta','embed-b');r.mark_verified(e,a,3)
  with self.assertRaisesRegex(ValueError,'测试'):v.rpc(e,'profile.activate',{'id':b['id']})
  self.assertEqual(v.config(e)['id'],a['id']);r.mark_verified(e,b,4)
  v.rpc(e,'profile.activate',{'id':b['id']});self.assertEqual(v.config(e)['model'],'embed-b')
  self.assertTrue(r.verified(e.ROOT,a));v.rpc(e,'profile.activate',{'id':a['id']});self.assertTrue(r.verified(e.ROOT))
  self.assertNotEqual(v.profile(a),v.profile(b));self.assertFalse((e.ROOT/'workspace').exists())
  v.rpc(e,'settings.save',{'id':a['id'],'apiKey':'changed'});self.assertFalse(r.verified(e.ROOT));self.assertTrue(r.verified(e.ROOT,b))
 def test_models_and_draft_test_use_selected_profile_only(self):
  import httpx
  a=self.create();b=self.create('Beta','embed-b',apiKey='beta-secret')
  with patch('httpx.get',return_value=httpx.Response(200,json={'data':[{'id':'embed-b'},{'id':'embed-b'}]})) as get:
   self.assertEqual(v.rpc(e,'models',{'id':b['id'],'baseUrl':'https://example.test/v1/embeddings'}),['embed-b'])
   self.assertIs(get.call_args.kwargs['trust_env'],False)
   self.assertEqual(get.call_args.args[0],'https://example.test/v1/models');self.assertEqual(get.call_args.kwargs['headers']['Authorization'],'Bearer beta-secret')
  before=(e.ROOT/'config/embedding.json').read_bytes()
  with patch.object(v,'embed',return_value=[[1,2,3]]) as embed:
   v.rpc(e,'test',{'id':b['id']});self.assertEqual(embed.call_args.args[1]['apiKey'],'beta-secret')
  self.assertEqual((e.ROOT/'config/embedding.json').read_bytes(),before);self.assertEqual(v.config(e)['id'],a['id'])
  for response in (httpx.Response(200,json=[]),httpx.Response(200,text='not json'),httpx.Response(200,json={'data':{}})):
   with patch('httpx.get',return_value=response),self.assertRaisesRegex(ValueError,'模型列表'):v.rpc(e,'models',{'id':b['id']})
 def test_delete_and_duplicate_names_are_scoped(self):
  a=self.create();b=self.create('Beta','embed-b')
  with self.assertRaisesRegex(ValueError,'名称已存在'):self.create('alpha','embed-c')
  with self.assertRaisesRegex(ValueError,'先'):v.rpc(e,'profile.delete',{'id':a['id']})
  v.rpc(e,'profile.delete',{'id':b['id']});self.assertEqual(v.config(e)['id'],a['id'])
  with self.assertRaises(ValueError):v.rpc(e,'profile.key',{'id':'../../config'})
  v.rpc(e,'profile.delete',{'id':a['id']});self.assertFalse(v.settings(e)['configured']);self.assertEqual(v.settings(e)['profiles'],[])

if __name__=='__main__':unittest.main()
