"""First-launch selection must never silently recreate an offline workspace."""
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage

class WorkspaceStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]/'tmp');self.root=Path(self.temp.name).resolve()/'app';self.root.mkdir()
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

    def project(self, base, folder, pid):
        data={'id':pid,'name':folder,'description':'Retained description','color':'#123456',
              'papers':[],'messages':[],'sections':[{'id':'s','title':'Saved','content':'Keep manuscript'}],
              'tasks':[],'notes':{'123':'Keep note'}}
        storage.atomic(base/folder/'project.json',data)
        (base/folder/'review').mkdir(exist_ok=True)
        (base/folder/'review/outline.csv').write_text('Saved outline')
        return data

    def test_fresh_install_imports_existing_workspace_without_writing_research(self):
        base=Path(self.temp.name).resolve()/'研究 文件夹'
        one=self.project(base,'旧项目','one');two=self.project(base,'Other','two')
        before={p.relative_to(base):p.read_bytes() for p in base.rglob('*') if p.is_file()}
        storage.select_workspace(self.root,str(base))
        self.assertEqual(storage.initialize(self.root)['discoveryWarnings'],[])
        state=storage.read_state(self.root)
        self.assertEqual({p['id']:p for p in state['projects']},{'one':one,'two':two})
        self.assertEqual(storage.project_dir(self.root,'one'),base/'旧项目')
        self.assertEqual(before,{p.relative_to(base):p.read_bytes() for p in base.rglob('*') if p.is_file()})
        with patch.object(storage,'atomic') as write:
            storage.initialize(self.root)
            write.assert_not_called()

    def test_previously_selected_workspace_merges_and_preserves_active_preferences(self):
        storage.initialize(self.root);base=self.root/'workspace'
        self.project(base,'Current','current');self.project(base,'Old','old')
        storage.atomic(self.root/'config/storage.json',{**storage.config(self.root),'projects':{'current':'Current'}})
        storage.atomic(self.root/'data/prototype/state.json',{'version':1,'projects':[{'id':'current'}],
                       'active':'current','theme':'dark','uiLanguage':'en','defaultContentLanguage':'en'})
        storage.initialize(self.root)
        state=storage.read_state(self.root)
        self.assertEqual([p['id'] for p in state['projects']],['current','old'])
        self.assertEqual((state['active'],state['theme'],state['uiLanguage']),('current','dark','en'))

    def test_legacy_default_workspace_with_lost_catalog(self):
        self.project(self.root/'workspace','Old','old')
        self.assertEqual(storage.bootstrap(self.root)['state'],'ready')
        storage.initialize(self.root)
        self.assertEqual(storage.read_state(self.root)['active'],'old')

    def test_invalid_duplicate_deleted_and_linked_projects_do_not_block_valid(self):
        storage.initialize(self.root);base=self.root/'workspace'
        self.project(base,'Valid','valid')
        self.project(base,'DuplicateA','dup');self.project(base,'DuplicateB','dup')
        self.project(base,'Gone','deleted');self.project(base/'.trash','Trashed','trash')
        self.project(base,'.deleting-test','staged')
        storage.atomic(base/'Broken/project.json',{'id':'broken'})
        storage.atomic(base/'Future/project.json',{'id':'future','version':2})
        (base/'BadJson').mkdir();(base/'BadJson/project.json').write_text('{')
        external=Path(self.temp.name)/'external';self.project(external,'External','external')
        (base/'Linked').symlink_to(external/'External',target_is_directory=True)
        (base/'LinkedFile').mkdir();(base/'LinkedFile/project.json').symlink_to(external/'External/project.json')
        storage.atomic(self.root/'config/storage.json',{**storage.config(self.root),'deletedProjects':{'deleted':{}}})
        warnings=storage.initialize(self.root)['discoveryWarnings']
        self.assertEqual([p['id'] for p in storage.read_state(self.root)['projects']],['valid'])
        self.assertEqual(len(warnings),6)
        self.assertTrue((base/'Gone/project.json').exists())

    def test_known_duplicate_uses_registered_folder(self):
        storage.initialize(self.root);base=self.root/'workspace'
        self.project(base,'Original','one');self.project(base,'Copy','one')
        storage.atomic(self.root/'config/storage.json',{**storage.config(self.root),'projects':{'one':'Original'}})
        self.assertEqual(len(storage.initialize(self.root)['discoveryWarnings']),1)
        self.assertEqual(storage.read_state(self.root)['projects'][0]['name'],'Original')

    def test_interrupted_catalog_commit_recovers_on_retry(self):
        storage.initialize(self.root);self.project(self.root/'workspace','Old','old')
        original=storage.atomic
        def fail_state(path,data):
            if path.name=='state.json':raise OSError('interrupted')
            original(path,data)
        with patch.object(storage,'atomic',side_effect=fail_state):
            with self.assertRaises(OSError):storage.initialize(self.root)
        storage.initialize(self.root)
        self.assertEqual(storage.read_state(self.root)['active'],'old')

    def test_corrupt_state_is_not_overwritten(self):
        storage.initialize(self.root);self.project(self.root/'workspace','Old','old')
        storage.atomic(self.root/'data/prototype/state.json',{'version':99,'projects':[]})
        with self.assertRaises(ValueError):storage.initialize(self.root)
        self.assertEqual(storage.config(self.root)['projects'],{})
        self.assertEqual(json.loads((self.root/'data/prototype/state.json').read_text())['version'],99)

    def test_offline_workspace_is_not_recreated_at_initialization(self):
        base=Path(self.temp.name)/'offline'
        storage.atomic(self.root/'config/storage.json',{'workspace':str(base),'projects':{},'migrated':True})
        with self.assertRaises(ValueError):storage.initialize(self.root)
        self.assertFalse(base.exists())

if __name__=='__main__':unittest.main()
