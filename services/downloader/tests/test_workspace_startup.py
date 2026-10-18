"""First-launch selection must never silently recreate an offline workspace."""
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage

class WorkspaceStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()/'app';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()
    def test_fresh_check_does_not_create_workspace(self):
        self.assertEqual(storage.bootstrap(self.root)['state'],'required')
        self.assertFalse((self.root/'workspace').exists())
        self.assertFalse((self.root/'config/storage.json').exists())
    def test_absolute_unicode_path_preserves_unrelated_files(self):
        target=Path(self.temp.name).resolve()/'论文 空间';target.mkdir();(target/'keep.txt').write_text('keep')
        storage.select_workspace(self.root,str(target))
        self.assertEqual(storage.bootstrap(self.root)['workspace'],str(target))
        self.assertEqual((target/'keep.txt').read_text(),'keep')
        self.assertFalse((self.root/'workspace').exists())
        with self.assertRaises(ValueError):storage.select_workspace(self.root,str(target/'other'))
    def test_relative_and_resources_rejected(self):
        for path in ['relative',str(self.root/'models/marker'),str(self.root)]:
            with self.assertRaises(ValueError):storage.select_workspace(self.root,path)
        self.assertFalse((self.root/'config/storage.json').exists())
    def test_existing_offline_workspace_requires_matching_projects(self):
        original=Path(self.temp.name).resolve()/'unmounted'
        storage.atomic(self.root/'config/storage.json',{'workspace':str(original),'projects':{'p':'Paper'},'migrated':True})
        self.assertEqual(storage.bootstrap(self.root)['state'],'unavailable')
        with self.assertRaises(ValueError):storage.select_workspace(self.root,str(Path(self.temp.name).resolve()/'empty'))
        moved=Path(self.temp.name).resolve()/'moved';(moved/'Paper').mkdir(parents=True)
        (moved/'Paper/project.json').write_text(json.dumps({'id':'p'}))
        storage.select_workspace(self.root,str(moved))
        self.assertEqual(storage.project_dir(self.root,'p'),moved/'Paper')
        self.assertFalse(original.exists())
    def test_existing_default_workspace_recognized(self):
        storage.initialize(self.root)
        self.assertEqual(storage.bootstrap(self.root)['state'],'ready')
        self.assertEqual(storage.bootstrap(self.root)['workspace'],str(self.root/'workspace'))

if __name__=='__main__':unittest.main()
