"""Offline installer safety tests; no production environment is changed."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import install_assets as assets

spec = importlib.util.spec_from_file_location('setup_runtime', Path(__file__).with_name('setup-runtime.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / 'services/downloader').mkdir(parents=True)
        (self.root / 'services/downloader/engine.py').touch()
        self.item = {'path': 'models/marker/test/config.json', 'bytes': 2,
                     'sha256': hashlib.sha256(b'{}').hexdigest()}

    def tearDown(self):
        self.temp.cleanup()

    def test_existing_environment_refused_without_changes(self):
        (self.root / 'runtimes/marker').mkdir(parents=True)
        sentinel = self.root / 'runtimes/marker/keep'
        sentinel.write_bytes(b'existing environment')
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup.platform, 'machine', return_value='arm64'):
            with self.assertRaisesRegex(ValueError, 'unmanaged'):
                setup.preflight(self.root, 'lock')
        self.assertEqual(sentinel.read_bytes(), b'existing environment')
        self.assertFalse((self.root / 'runtimes/install-state.json').exists())

    def test_system_proxy_is_scoped_to_children(self):
        with patch.dict(setup.os.environ, {}, clear=True), patch.object(setup.urllib.request, 'getproxies', return_value={'https': 'http://127.0.0.1:1234'}):
            env = setup.environment(self.root)
            self.assertEqual(env['HTTPS_PROXY'], 'http://127.0.0.1:1234')
            self.assertNotIn('HTTPS_PROXY', setup.os.environ)
        with patch.dict(setup.os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:5678'}, clear=True), patch.object(setup.urllib.request, 'getproxies', return_value={'https': 'http://127.0.0.1:1234'}):
            self.assertEqual(setup.environment(self.root)['HTTPS_PROXY'], 'http://127.0.0.1:5678')

    def test_only_matching_owned_install_can_resume(self):
        (self.root / 'runtimes').mkdir()
        state = self.root / 'runtimes/install-state.json'
        state.write_text(json.dumps({'schemaVersion': 1, 'fingerprint': 'lock', 'done': ['node']}))
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup.platform, 'machine', return_value='arm64'):
            self.assertEqual(setup.preflight(self.root, 'lock')['done'], ['node'])
            with self.assertRaisesRegex(ValueError, 'differs'):
                setup.preflight(self.root, 'new lock')

    def test_corrupt_stream_never_published(self):
        path = assets.destination(self.root, self.item['path'])
        with self.assertRaises(ValueError):
            assets.receive(io.BytesIO(b'bad data'), path, self.item)
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.iterdir()), [])

    def test_existing_different_file_not_overwritten(self):
        path = assets.destination(self.root, self.item['path'])
        path.parent.mkdir(parents=True)
        path.write_bytes(b'user file')
        with self.assertRaisesRegex(ValueError, 'differs'):
            assets.receive(io.BytesIO(b'{}'), path, self.item)
        self.assertEqual(path.read_bytes(), b'user file')

    def test_archive_exact_allowlist_and_resume(self):
        pack = self.root / 'pack.zip'
        with zipfile.ZipFile(pack, 'w') as z:
            z.writestr(self.item['path'], b'{}')
            z.writestr('../escaped.txt', b'not extracted')
            z.writestr('config/embedding.json', b'not extracted')
        assets.install(self.root, [self.item], pack)
        assets.install(self.root, [self.item], pack)
        self.assertTrue(assets.matches(self.root / self.item['path'], self.item))
        self.assertFalse((self.root / 'config').exists())
        self.assertFalse((self.root.parent / 'escaped.txt').exists())

    def test_symlink_resource_refused(self):
        (self.root / 'models').symlink_to(self.root / 'services', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            assets.destination(self.root, self.item['path'])

    def test_missing_pack_member_fails_before_writing(self):
        pack = self.root / 'pack.zip'
        with zipfile.ZipFile(pack, 'w'):
            pass
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            assets.install(self.root, [self.item], pack)
        self.assertFalse((self.root / 'models').exists())


if __name__ == '__main__':
    unittest.main()
