import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import compact_io as compact
import engine as e
import snapshot_files
import storage


class CompactIOTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_new_records_are_compressed_from_first_write_and_read_after_move(self):
        path=self.root/'run/input.json'
        value={'question':'历史问题','evidence':['Evidence 中文 '*3000]*3}
        target=compact.write_json(e,path,value)
        self.assertFalse(path.exists())
        self.assertLess(target.stat().st_size,len(json.dumps(value).encode())/10)
        self.assertEqual(compact.read_json(path),value)
        moved=self.root/'moved';path.parent.rename(moved)
        self.assertEqual(compact.read_json(moved/'input.json'),value)
        self.assertEqual(compact.read_json(moved/'missing.json',{}),{})

    def test_legacy_override_and_failed_write_keep_original(self):
        path=self.root/'input.json';e.write_json(path,{'old':True})
        with patch.object(e,'atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):compact.write_json(e,path,{'new':True})
        self.assertEqual(compact.read_json(path),{'old':True})
        compact.write_json(e,path,{'new':True})
        self.assertFalse(path.exists());self.assertEqual(compact.read_json(path),{'new':True})
        e.write_json(path,{'fixtureOverride':True})
        self.assertEqual(compact.read_json(path),{'fixtureOverride':True})
        path.unlink();compact.compressed_path(path).write_bytes(b'broken archive')
        with self.assertRaises(gzip.BadGzipFile):compact.read_json(path,{})

    def test_snapshot_fallback_reuse_and_integrity(self):
        source=self.root/'source.png';target=self.root/'images/snapshot.png';source.write_bytes(b'image')
        with patch.object(snapshot_files,'clone',return_value=False):
            snapshot_files.save_image(source,target,b'image',e.atomic)
        source.write_bytes(b'changed');self.assertEqual(target.read_bytes(),b'image')
        with patch.object(snapshot_files,'clone',side_effect=AssertionError('no second copy')):
            snapshot_files.save_image(source,target,b'image',e.atomic)
        with self.assertRaisesRegex(ValueError,'校验'):
            snapshot_files.save_image(source,target,b'changed',e.atomic)

    @unittest.skipUnless(sys.platform=='darwin','APFS clonefile is a macOS optimization')
    def test_real_clone_is_independent_after_in_place_edit_and_source_removal(self):
        source=self.root/'source.png';target=self.root/'snapshot.png';data=b'image-data'*16384
        source.write_bytes(data)
        with patch.object(snapshot_files,'clone',wraps=snapshot_files.clone) as clone:
            with patch.object(e,'atomic',side_effect=AssertionError('expected filesystem sharing')):
                snapshot_files.save_image(source,target,data,e.atomic)
            self.assertEqual(clone.call_count,1)
        self.assertNotEqual(source.stat().st_ino,target.stat().st_ino)
        with source.open('r+b') as stream:stream.write(b'edited')
        self.assertEqual(target.read_bytes(),data)
        source.unlink();self.assertEqual(target.read_bytes(),data)

    def test_racing_source_edit_falls_back_to_captured_bytes(self):
        source=self.root/'source.png';target=self.root/'snapshot.png';source.write_bytes(b'old')
        def changed_clone(src,dest):dest.write_bytes(b'new');return True
        with patch.object(snapshot_files,'clone',side_effect=changed_clone):
            snapshot_files.save_image(source,target,b'old',e.atomic)
        self.assertEqual(target.read_bytes(),b'old');self.assertFalse(list(self.root.glob('*.tmp')))

    def test_project_move_preserves_compressed_records_with_copy_fallback(self):
        app=self.root/'app';base=app/'workspace/test';storage.layout(base)
        storage.atomic(app/'config/storage.json',{'workspace':str(base.parent),'projects':{'test':'test'},'migrated':True})
        compact.write_json(e,base/'review/Review/logs/run/input.json',{'topic':'保留历史'})
        e.atomic(base/'markdown/assets/1/figure.png',b'original image')
        target=self.root/'moved'
        with patch.object(snapshot_files,'clone',return_value=False):
            storage.move_workspace(app,str(target))
        self.assertFalse(base.exists())
        self.assertEqual(compact.read_json(target/'test/review/Review/logs/run/input.json'),{'topic':'保留历史'})
        self.assertEqual((target/'test/markdown/assets/1/figure.png').read_bytes(),b'original image')
        self.assertEqual(storage.project_dir(app,'test'),target/'test')

    def test_project_move_failed_copy_keeps_old_location(self):
        app=self.root/'app';base=app/'workspace/test';storage.layout(base)
        storage.atomic(app/'config/storage.json',{'workspace':str(base.parent),'projects':{'test':'test'},'migrated':True})
        e.atomic(base/'markdown/1.md','Original')
        target=self.root/'failed'
        def bad_copy(source,destination):Path(destination).write_bytes(b'corrupt')
        with patch.object(snapshot_files,'copy2',side_effect=bad_copy):
            with self.assertRaisesRegex(ValueError,'校验'):storage.move_workspace(app,str(target))
        self.assertEqual((base/'markdown/1.md').read_text(),'Original')
        self.assertEqual(storage.project_dir(app,'test'),base)
        self.assertFalse((target/'test').exists())


if __name__=='__main__':unittest.main()
