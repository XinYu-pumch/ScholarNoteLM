import hashlib,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_materials import Guard,InputsChanged
import storage


class MaterialGuardTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.e=SimpleNamespace(ROOT=self.root,PROJECT='test');self.project=storage.project_dir(self.root,'test')
 def tearDown(self):self.tmp.cleanup()
 def test_unchanged_dependencies_do_not_recompute(self):
  compute=Mock(return_value='original');guard=Guard(self.e,'original',compute)
  for _ in range(8):guard.verify()
  self.assertEqual(compute.call_count,1)
 def test_material_and_model_changes_invalidate_including_restored_mtime(self):
  names=['pubmed/current.xml','markdown/1.md','markdown/raw/1.md','pdf/1.pdf','markdown/assets/1/figure.png','metadata/markdown/1.json','metadata/corpus-membership.json','metadata/index-generation.json','metadata/conversion-settings.json','metadata/index-cleared.json']
  paths=[self.project/n for n in names]+[self.root/'config/embedding.json']
  for p in paths:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'old')
  for p in paths:
   with self.subTest(path=str(p)):
    compute=lambda:hashlib.sha256(b''.join(f.read_bytes() for f in paths)).hexdigest()
    guard=Guard(self.e,compute(),compute);guard.verify();stat=p.stat()
    p.write_bytes(b'new');os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    with self.assertRaises(InputsChanged):guard.verify()
    p.write_bytes(b'old')
 def test_continuously_changing_sources_are_not_cached(self):
  p=self.project/'pubmed/current.xml';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('start')
  def racing():p.write_text(p.read_text()+'x');return 'original'
  guard=Guard(self.e,'original',racing)
  with self.assertRaises(InputsChanged):guard.verify()
  self.assertIsNone(guard.validated)
 def test_failed_computation_is_not_cached(self):
  compute=Mock(side_effect=[ValueError('incomplete'),'original']);guard=Guard(self.e,'original',compute)
  with self.assertRaises(ValueError):guard.verify()
  guard.verify();self.assertEqual(compute.call_count,2)
