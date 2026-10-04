"""Isolated storage + real Rust RPC checks. Never touches user projects."""
import copy,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/downloader'))
import storage

class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='project-delete-',dir=ROOT/'tmp');self.root=Path(self.temp.name)
        for name in ('services','runtimes'):(self.root/name).symlink_to(ROOT/name,target_is_directory=True)
        self.projects=[dict(id=k,name=k,color='purple',description='',papers=[],notes={},sections=[],tasks=[],messages=[]) for k in ('First','Second')]
        for p in self.projects:storage.register(self.root,dict(project=p['id'],folder=p['id'],data=p))
        self.state=dict(version=1,active='First',theme='light',projects=self.projects)
        storage.write_state(self.root,self.state)
        cfg=storage.config(self.root);cfg['migrated']=True;storage.atomic(self.root/'config/storage.json',cfg)
        self.first=storage.project_dir(self.root,'First');self.second=storage.project_dir(self.root,'Second')
        for name in ('pdf/1.pdf','markdown/1.md','vectors/payload','notes/note.md','review/draft.txt'):
            (self.first/name).parent.mkdir(parents=True,exist_ok=True);(self.first/name).write_bytes(name.encode())
    def tearDown(self):self.temp.cleanup()
    def rpc(self,action,success=True,**args):
        result=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps(dict(action=action,args=args)),text=True,capture_output=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(self.root)},timeout=30)
        value=json.loads(result.stdout);self.assertEqual(value['ok'],success,value)
        return value.get('data') if success else value['error']
    def delete(self,pid='First'):return self.rpc('storage.delete',project=pid,confirm=pid)
    def test_delete_removes_files_preserves_other_project_and_blocks_stale_requests(self):
        old=copy.deepcopy(self.state);second=(self.second/'project.json').read_bytes()
        result=self.delete();self.assertTrue(result['deleted'])
        self.assertFalse(self.first.exists());self.assertEqual(result['state']['active'],'Second')
        self.assertEqual([p.name for p in (self.root/'workspace').iterdir()],['Second'])
        self.assertEqual((self.second/'project.json').read_bytes(),second)
        self.rpc('storage.state.write',success=False,state=old)
        self.rpc('storage.register',success=False,project='First',folder='Resurrect',data=self.projects[0])
        self.rpc('workspace',success=False,project='First')
        self.rpc('download.status',success=False,project='First')
        with self.assertRaisesRegex(ValueError,'已删除'):storage.project_dir(self.root,'First')
        self.assertFalse(self.first.exists());self.assertEqual(self.rpc('storage.state.read')['active'],'Second')
    def test_last_project_empty_state_and_recreate(self):
        self.delete();result=self.delete('Second');self.assertEqual(result['state']['projects'],[]);self.assertEqual(result['state']['active'],'')
        self.rpc('storage.initialize');empty=self.rpc('storage.state.read');self.assertEqual(empty['projects'],[])
        self.rpc('storage.state.write',state=empty)
        project={**self.projects[0],'id':'Third'}
        self.rpc('storage.register',project='Third',folder='First',data=project)
        self.rpc('storage.state.write',state={**empty,'active':'Third','projects':[project]})
        self.assertEqual(self.rpc('storage.state.read')['active'],'Third')
    def test_confirmation_and_symlink_rejected(self):
        self.rpc('storage.delete',success=False,project='First',confirm='Second');self.assertTrue(self.first.exists())
        parked=self.first.with_name('Parked');self.first.rename(parked);self.first.symlink_to(self.second,target_is_directory=True)
        self.rpc('storage.delete',success=False,project='First',confirm='First');self.assertTrue(self.first.exists())
        self.assertEqual(len(storage.config(self.root)['projects']),2)
    def test_unicode_paths_work_through_real_rpc(self):
        p={**self.projects[0],'id':'Chinese'}
        name='中文_研究2026'
        self.rpc('storage.register',project='Chinese',folder=name,data=p)
        self.assertEqual(Path(self.rpc('storage.status',project='Chinese')['projectPath']).name,name)
        self.rpc('workspace',project='Chinese')
        self.rpc('review.create',project='Chinese',name='免疫_综述',outlineSource='file',csv='1,引言\n')
        self.assertEqual(self.rpc('review.list',project='Chinese')['workspaces'][0]['name'],'免疫_综述')
        for invalid in ('CON','nul','a/b','a b','a.','中文'*33):
            self.rpc('storage.register',success=False,project='Invalid',folder=invalid,data=p)
        self.rpc('storage.register',success=False,project='Duplicate',folder='中文_研究2026',data=p)
        self.rpc('storage.state.write',state={**self.state,'projects':self.projects+[p]})
        self.delete('Chinese');self.assertFalse((self.root/'workspace'/name).exists())
    def test_internal_symlink_does_not_delete_target(self):
        (self.first/'external').symlink_to(self.second,target_is_directory=True)
        self.delete();self.assertTrue((self.second/'project.json').exists())
    def test_failed_removal_can_retry_without_false_success(self):
        def partial_failure(path):
            (path/'project.json').unlink()
            raise PermissionError('file in use')
        with patch.object(storage.shutil,'rmtree',side_effect=partial_failure):
            with self.assertRaisesRegex(ValueError,'删除未完成'):storage.delete_project(self.root,dict(project='First',confirm='First'))
        self.assertEqual(storage.read_state(self.root)['active'],'First')
        self.assertTrue((self.first/'pdf/1.pdf').exists())
        self.delete();self.assertFalse(self.first.exists())
    def test_busy_storage_blocks_delete(self):
        with storage.file_lock(self.root/'config/storage.lock',shared=True):
            error=self.rpc('storage.delete',success=False,project='First',confirm='First')
            self.assertIn('正在使用',error)
        self.assertTrue(self.first.exists());self.delete()
    def test_queued_coordinator_blocks_delete(self):
        storage.atomic(self.first/'metadata/library-job.json',dict(id='pending',state='queued',pid=0,created=time.time()))
        error=self.rpc('storage.delete',success=False,project='First',confirm='First');self.assertIn('任务',error)
        self.assertTrue(self.first.exists())
    def test_failed_catalog_commit_rolls_back_folder(self):
        original=storage.atomic
        def fail(path,data):
            if path==self.root/'config/storage.json':raise OSError('simulated full disk')
            original(path,data)
        with patch.object(storage,'atomic',side_effect=fail):
            with self.assertRaises(OSError):storage.delete_project(self.root,dict(project='First',confirm='First'))
        self.assertTrue((self.first/'pdf/1.pdf').is_file());self.assertIn('First',storage.config(self.root)['projects'])
        self.assertEqual(storage.read_state(self.root)['active'],'First')

if __name__=='__main__':unittest.main(verbosity=2)
