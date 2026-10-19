"""Source pairing failures are detected before launching an incompatible backend."""
import json
from pathlib import Path
import tempfile
import unittest
from release_manifest import sha,validate,check_app,export_source
import subprocess,zipfile

class PairingTests(unittest.TestCase):
    def test_missing_changed_and_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'source.py';p.write_text('original')
            manifest={'files':{'source.py':sha(p)}}
            validate(root,manifest)
            p.write_text('changed')
            with self.assertRaises(ValueError):validate(root,manifest)
            p.unlink()
            with self.assertRaises(ValueError):validate(root,manifest)
            with self.assertRaises(ValueError):validate(root,{'files':{'../outside':'bad'}})
    def test_source_zip_excludes_ignored_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'.gitignore').write_text('runtimes/\n')
            (root/'package.json').write_text('{"version":"test"}')
            (root/'runtimes').mkdir();(root/'runtimes/private').write_text('fixture')
            with tempfile.TemporaryDirectory() as output:
                archive=export_source(root,Path(output))
                with zipfile.ZipFile(archive) as z:
                    self.assertIn('ScholarNoteLM/package.json',z.namelist())
                    self.assertFalse(any('/runtimes/' in p or '/.git/' in p for p in z.namelist()))
    def test_tracked_private_folder_blocks_source_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'package.json').write_text('{"version":"test"}')
            (root/'config').mkdir();(root/'config/fixture.json').write_text('{}')
            with tempfile.TemporaryDirectory() as output:
                with self.assertRaises(ValueError):export_source(root,Path(output))
    def test_app_without_manifest_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'ScholarNoteLM.app').mkdir()
            with self.assertRaises(ValueError):check_app(root,platform='darwin')
    def test_windows_exe_requires_matching_source_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'ScholarNoteLM.exe').write_bytes(b'fixture')
            with self.assertRaises(ValueError):check_app(root,platform='win32')
            (root/'source.py').write_bytes(b'matching')
            (root/'source-manifest.json').write_text(json.dumps({'files':{'source.py':sha(root/'source.py')}}))
            check_app(root,platform='win32')
            (root/'source.py').write_bytes(b'changed')
            with self.assertRaises(ValueError):check_app(root,platform='win32')

if __name__=='__main__':unittest.main()
