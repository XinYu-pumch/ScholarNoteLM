"""Project binding never copies credentials and never follows a global switch."""
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage,embedding_profiles as profiles,project_embedding as binding,vector_service as vectors,retrieval_settings as retrieval

class ProjectEmbeddingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]/'tmp')
  self.root=Path(self.tmp.name);self.e=SimpleNamespace(ROOT=self.root,PROJECT='one',write_json=storage.atomic)
  self.a={**vectors.DEFAULTS,'id':'a','name':'A','baseUrl':'https://a.example/v1','model':'embedding-a','apiKey':'fixture-secret-a'}
  self.b={**self.a,'id':'b','name':'B','baseUrl':'https://b.example/v1','model':'embedding-b','apiKey':'fixture-secret-b'}
  profiles.write(self.e,{'profiles':[self.a,self.b],'activeProfile':'a'})
  storage.register(self.root,{'project':'one','folder':'One','data':{'id':'one'}})
 def tearDown(self):self.tmp.cleanup()
 def test_existing_project_does_not_follow_global_default(self):
  profiles.activate(self.e,'b');self.assertEqual(vectors.config(self.e)['model'],'embedding-a')
  storage.register(self.root,{'project':'two','folder':'Two','data':{'id':'two'}})
  other=SimpleNamespace(ROOT=self.root,PROJECT='two')
  self.assertEqual(vectors.config(other)['model'],'embedding-b')
  binding.bind(self.e,self.b);self.assertEqual(vectors.config(self.e)['model'],'embedding-b')
 def test_unbound_project_pinned_before_global_switch(self):
  binding.path(self.e).unlink();profiles.activate(self.e,'b')
  self.assertEqual(vectors.config(self.e)['model'],'embedding-a')
 def test_provider_identity_frozen_but_keys_and_limits_live(self):
  profiles.save(self.e,{**self.a,'model':'new-a','apiKey':'rotated-fixture-secret','rpm':100,'tpm':100000})
  cfg=vectors.config(self.e)
  self.assertEqual(cfg['model'],'embedding-a');self.assertEqual(cfg['apiKey'],'rotated-fixture-secret');self.assertEqual(cfg['rpm'],100)
  text=binding.path(self.e).read_text();self.assertNotIn('secret',text);self.assertNotIn('apiKey',text)
  snap=retrieval.snapshot(self.root,'one');self.assertEqual(snap['embeddingModel']['model'],'embedding-a');self.assertNotIn('secret',json.dumps(snap))
 def test_deleted_profile_does_not_silently_use_other_model(self):
  profiles.activate(self.e,'b');profiles.delete(self.e,'a')
  cfg=vectors.config(self.e);self.assertEqual(cfg['model'],'embedding-a');self.assertEqual(cfg['apiKey'],'')
if __name__=='__main__':unittest.main()
