import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as e
import manuscript_storage as images
import project_compaction as compact
import review_manuscripts as m
import test_review_manuscripts as fixture
import storage


class CompactionTests(unittest.TestCase):
    setUp = fixture.ManuscriptTests.setUp
    tearDown = fixture.ManuscriptTests.tearDown

    def legacy(self, tag='A'):
        # Enough deterministic incompressible image data to expose repeated storage.
        raw = b''.join(hashlib.sha256(str(i).encode()).digest() for i in range(400))
        url = 'data:image/png;base64,' + base64.b64encode(raw).decode()
        value = {'topic': tag, 'rows': [], 'sections': {}, 'blocks': {}, 'pmids': [],
                 'references': {str(i): {'dataUrl': url, 'caption': str(i)} for i in range(12)},
                 'outlineHash': 'outline', 'partial': False, 'models': []}
        value.update(id=m.payload_hash(value), created=1, label=tag)
        target = self.path/'manuscripts'/value['id']/'document.json'
        e.write_json(target, value)
        return value, target

    def test_migration_shares_images_keeps_ids_and_is_idempotent(self):
        a, pa = self.legacy(); b, pb = self.legacy('B')
        originals = pa.read_bytes(), pb.read_bytes()
        report = compact.compact_project(e)
        self.assertEqual((pa.read_bytes(), pb.read_bytes()), originals)
        self.assertFalse((self.path/'manuscripts/assets').exists())
        self.assertGreater(report['savedBytes'], report['beforeBytes']*.8)
        report = compact.compact_project(e, True)
        self.assertEqual(m.get(e, 'Test', a['id']), a)
        self.assertEqual(m.get(e, 'Test', b['id']), b)
        assets = list((self.path/'manuscripts/assets').glob('*.gz'))
        self.assertEqual(len(assets), 1)
        self.assertEqual(pa.stat().st_size+pb.stat().st_size+assets[0].stat().st_size, report['afterBytes'])
        self.assertEqual(compact.compact_project(e, True)['savedBytes'], 0)

    def test_legacy_read_is_readonly_and_new_save_is_compact(self):
        a, path = self.legacy(); before = path.read_bytes()
        self.assertEqual(m.get(e, 'Test', a['id']), a)
        self.assertEqual(path.read_bytes(), before)
        with patch.object(m, 'capture', return_value={k:v for k,v in a.items() if k not in ('id','created','label')}):
            self.assertEqual(m.save(e, 'Test'), a)
        self.assertEqual(json.loads(path.read_text())['storageFormat'], images.FORMAT)
        with patch.object(m, 'capture', return_value={**{k:v for k,v in a.items() if k not in ('id','created','label')},'topic':'new'}):
            new = m.save(e, 'Test')
        self.assertEqual(m.get(e, 'Test', new['id']), new)
        self.assertEqual(len(list((self.path/'manuscripts/assets').glob('*.gz'))), 1)

    def test_image_corruption_missing_and_symlink_are_rejected(self):
        a, path = self.legacy(); compact.compact_project(e, True)
        asset = next((self.path/'manuscripts/assets').glob('*.gz')); raw = asset.read_bytes()
        asset.write_bytes(gzip.compress(b'changed'))
        with self.assertRaisesRegex(ValueError, '校验'):m.get(e, 'Test', a['id'])
        asset.unlink()
        with self.assertRaisesRegex(ValueError, '缺失'):m.get(e, 'Test', a['id'])
        outside = e.ROOT/'outside.gz';outside.write_bytes(raw);asset.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, '符号链接'):m.get(e, 'Test', a['id'])
        asset.unlink();asset.write_bytes(raw)
        stored=json.loads(path.read_text());stored['payload']['references']['0']['dataUrl']['imageAsset']='../outside'
        e.write_json(path,stored)
        with self.assertRaisesRegex(ValueError, '校验'):m.get(e, 'Test', a['id'])

    def test_write_failure_keeps_original_and_retry_works(self):
        a, path = self.legacy(); before = path.read_bytes()
        with patch.object(e, 'write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):compact.compact_project(e, True)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(m.get(e,'Test',a['id']),a)
        compact.compact_project(e,True);self.assertEqual(m.get(e,'Test',a['id']),a)

    def test_jsonl_preserved_byte_for_byte_without_reindexing_or_html_edits(self):
        self.legacy()
        path=self.base/'vectors/chunks/123.jsonl'
        original=(json.dumps({'text':'研究结果','metadata':{'abstract':'long '*1000}},ensure_ascii=False)+'\n').encode()
        e.atomic(path,original);html=self.path/'exports/original.html';e.atomic(html,b'unchanged self-contained HTML')
        database=self.base/'vectors/chunks.sqlite3';e.atomic(database,b'opaque untouched database')
        report=compact.compact_project(e,True)
        self.assertEqual(report['jsonlFiles'],1);self.assertFalse(path.exists())
        self.assertEqual(gzip.decompress(path.with_suffix('.jsonl.gz').read_bytes()),original)
        self.assertEqual(html.read_bytes(),b'unchanged self-contained HTML')
        self.assertEqual(database.read_bytes(),b'opaque untouched database')
        self.assertEqual(compact.compact_project(e,True)['savedBytes'],0)

    def test_conflicting_archive_or_bad_manuscript_prevents_replacement(self):
        a, path=self.legacy();before=path.read_bytes()
        source=self.base/'vectors/chunks/123.jsonl';e.atomic(source,b'original')
        e.atomic(source.with_suffix('.jsonl.gz'),gzip.compress(b'different'))
        with self.assertRaisesRegex(ValueError,'不同'):compact.compact_project(e,True)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(source.read_bytes(),b'original')
        bad=copy.deepcopy(a);bad['topic']='corrupt';e.write_json(path,bad)
        with self.assertRaisesRegex(ValueError,'校验'):compact.compact_project(e,True)

    def test_compact_snapshot_moves_with_workspace_and_exports_embedded_html(self):
        a,_=self.legacy();compact.compact_project(e,True)
        moved=self.base/'review/Moved';shutil.copytree(self.path,moved);shutil.rmtree(self.path)
        self.assertEqual(m.get(e,'Moved',a['id']),a)
        result=m.export(e,'Moved','html',a['id'])
        html=Path(result['path']).read_text()
        self.assertIn(a['references']['0']['dataUrl'],html)
        self.assertNotIn('imageAsset',html);self.assertNotIn('.data-url.gz',html)
        destination=e.ROOT/'standalone.html';shutil.copyfile(result['path'],destination)
        shutil.rmtree(moved)
        self.assertIn(a['references']['0']['dataUrl'],destination.read_text())

    def test_cli_defaults_to_readonly_and_refuses_active_storage_lock(self):
        _,path=self.legacy();original=path.read_bytes()
        storage.atomic(e.ROOT/'config/storage.json',{'workspace':str(self.base.parent),'projects':{'test':'test'},'migrated':True})
        script=Path(__file__).resolve().parents[3]/'scripts/compact-project-storage.py'
        command=[sys.executable,str(script),'--root',str(e.ROOT),'--project','test']
        result=subprocess.run(command,capture_output=True,text=True,check=True)
        self.assertFalse(json.loads(result.stdout)['applied']);self.assertEqual(path.read_bytes(),original)
        with storage.file_lock(e.ROOT/'config/storage.lock',shared=True):
            result=subprocess.run([*command,'--apply'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
        self.assertEqual(path.read_bytes(),original)
        result=subprocess.run([*command,'--apply'],capture_output=True,text=True,check=True)
        self.assertTrue(json.loads(result.stdout)['applied'])
        self.assertEqual(json.loads(path.read_text())['storageFormat'],images.FORMAT)


if __name__=='__main__':unittest.main()
