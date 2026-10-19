"""Packaging safety tests and optional offline check of an extracted Mac app."""
import argparse
import importlib.util
import json
import os
import plistlib
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap = load('macos_bootstrap', HERE/'standalone/macos-bootstrap.py')
builder = load('macos_builder', HERE/'build-macos-standalone.py')


class PackageTests(unittest.TestCase):
    def fixture(self, base):
        app = base/'Original.app'
        payload = app/'Contents/Resources/payload'
        (payload/'services').mkdir(parents=True)
        (payload/'services/fixture.py').write_text('pass\n')
        (app/'Contents/Resources/standalone-manifest.json').write_text(json.dumps({
            'schemaVersion': 1, 'platform': 'macos-arm64', 'files': builder.records(payload)}))
        return app

    def standalone(self, app, label):
        (app/'Contents/Resources').mkdir(parents=True)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.scholarnotelm.standalone'}))
        (app/'Contents/Resources/standalone-manifest.json').write_text('{}')
        (app/'label').write_text(label)

    def test_only_final_app_remains_and_failed_rebuild_preserves_it(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as name:
            base=Path(name);source=base/'Source.app';output=base/'output'
            (source/'Contents/Resources').mkdir(parents=True)
            (source/'Contents/Resources/source-manifest.json').write_text('{"version":"fixture"}')
            def assemble(_source, app, *_args):self.standalone(app,'new')
            with patch.object(builder.sys,'platform','darwin'),patch.object(builder.platform,'machine',return_value='arm64'),patch.object(builder,'validate'),patch.object(builder,'assets_manifest',return_value=[]),patch.object(builder,'assemble',side_effect=assemble):
                app=builder.build(source,output)
                self.assertEqual(list(output.iterdir()),[app])
                (app/'label').write_text('previous')
                with patch.object(builder,'assemble',side_effect=RuntimeError('failed build')):
                    with self.assertRaisesRegex(RuntimeError,'failed build'):builder.build(source,output)
                self.assertEqual((app/'label').read_text(),'previous')
                self.assertEqual(list(output.iterdir()),[app])
                builder.build(source,output)
                self.assertEqual((app/'label').read_text(),'new')
                self.assertEqual(list(output.iterdir()),[app])

    def test_publish_failure_restores_previous_app(self):
        with tempfile.TemporaryDirectory() as name:
            base=Path(name);target=base/'ScholarNoteLM.app';self.standalone(target,'previous')
            with self.assertRaises(FileNotFoundError):builder.publish(base/'missing.app',target)
            self.assertEqual((target/'label').read_text(),'previous')
            self.assertEqual(list(base.iterdir()),[target])

    def test_foreign_output_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as name:
            base=Path(name);target=base/'ScholarNoteLM.app';target.mkdir();(target/'keep').write_text('precious')
            with self.assertRaises(ValueError):builder.publish(base/'replacement.app',target)
            self.assertEqual((target/'keep').read_text(),'precious')

    def test_relocation_preserves_state_and_never_writes_app(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name);app = self.fixture(base);root = base/'state'
            before = builder.records(app/'Contents/Resources/payload')
            bootstrap.prepare(app, root)
            (root/'config/fixture.json').write_text('preserve settings')
            moved = base/'中文 空格.app';app.rename(moved)
            bootstrap.prepare(moved, root)
            self.assertEqual((root/'config/fixture.json').read_text(), 'preserve settings')
            self.assertEqual((root/'services/fixture.py').read_text(), 'pass\n')
            self.assertEqual(before, builder.records(moved/'Contents/Resources/payload'))
            self.assertFalse((moved/'Contents/Resources/payload/config').exists())

    def test_foreign_state_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name);app = self.fixture(base);root = base/'state';root.mkdir()
            (root/'precious').write_text('untouched')
            with self.assertRaises(ValueError):bootstrap.prepare(app, root)
            self.assertEqual(list(root.iterdir()), [root/'precious'])

    def test_real_resource_directory_is_not_removed(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name);app = self.fixture(base);root = base/'state'
            bootstrap.prepare(app, root)
            (root/'services').unlink();(root/'services').mkdir()
            (root/'services/precious').write_text('untouched')
            with self.assertRaises(ValueError):bootstrap.prepare(app, root)
            self.assertEqual((root/'services/precious').read_text(), 'untouched')

    def test_runtime_links_cannot_escape_the_package(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name);app = self.fixture(base);payload = app/'Contents/Resources/payload'
            (payload/'external').symlink_to('/usr/bin/python3')
            with self.assertRaises(ValueError):builder.records(payload)

    def test_tampered_package_is_rejected_before_runtime_execution(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name);app = self.fixture(base);root = base/'state'
            metadata = bootstrap.prepare(app, root)
            (app/'Contents/Resources/payload/services/fixture.py').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'Changed resource'):
                bootstrap.verify(app, root, metadata)

    def test_environment_removes_global_python_settings(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'PYTHONHOME':'/bad','PYTHONPATH':'/bad','CONDA_PREFIX':'/bad'}):
            env = bootstrap.environment(Path('/isolated'))
            self.assertNotIn('PYTHONHOME', env)
            self.assertNotIn('PYTHONPATH', env)
            self.assertNotIn('CONDA_PREFIX', env)
            self.assertEqual(env['SCHOLARNOTELM_ROOT'], '/isolated')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path)
    parser.add_argument('--state', type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PackageTests))
    if not result.wasSuccessful():raise SystemExit(1)
    if args.app:
        if not args.state:parser.error('--app requires an explicit disposable --state folder')
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(args.app)],check=True)
        env = {**os.environ, 'SCHOLARNOTELM_STANDALONE_HOME':str(args.state.absolute()),
               'PYTHONHOME':'/nonexistent-global-python', 'PYTHONPATH':'/nonexistent-global-packages',
               'PATH':'/usr/bin:/bin:/usr/sbin:/sbin',
               'HTTP_PROXY':'http://127.0.0.1:1', 'HTTPS_PROXY':'http://127.0.0.1:1'}
        subprocess.run([str(args.app.resolve()/'Contents/MacOS/scholarnotelm'),'--check'],
                       env=env,cwd='/private/tmp',check=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(args.app)],check=True)
