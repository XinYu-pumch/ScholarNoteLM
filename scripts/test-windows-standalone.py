"""Packaging boundary tests; optional smoke check of a disposable installation.

Never points tests at the developer's source installation or research directory.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/standalone'))
import bootstrap
spec = importlib.util.spec_from_file_location('standalone_build',ROOT/'scripts/build-windows-standalone.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PackageBoundaries(unittest.TestCase):
    def test_manifest_cannot_escape_or_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            for value in ('../config/keys', '/tmp/file', 'C:/secret', 'app\\config', 'app/../config', 'app//file', './file'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    bootstrap.safe_path(Path(folder),value)

    def test_copied_runtime_excludes_nonportable_entrypoints(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            included=('Scripts/python.exe','Scripts/pythonw.exe','Lib/site-packages/package/code.py','Lib/site-packages/package/LICENSE')
            excluded=('pyvenv.cfg','Scripts/pip.exe','Scripts/activate','Lib/site-packages/package/__pycache__/code.pyc')
            for name in included+excluded:
                file=root/'runtimes/downloader'/name
                file.parent.mkdir(parents=True,exist_ok=True)
                file.write_bytes(b'fixture')
            actual={p.relative_to(root/'runtimes/downloader').as_posix() for p in builder.runtime_files(root,'downloader')}
            self.assertEqual(actual,set(included))

    def test_integrity_failure_precedes_running_any_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'app';root.mkdir()
            (root/'fixture').write_bytes(b'changed')
            record={'files':{'app/fixture':{'bytes':7,'sha256':'0'*64}}}
            with self.assertRaisesRegex(ValueError,'damaged or changed'):
                bootstrap.verify(root,record)

    def test_environment_does_not_depend_on_developer_python(self):
        from unittest.mock import patch
        with patch.dict(os.environ,{'PYTHONHOME':'bad','PYTHONPATH':'bad','VIRTUAL_ENV':'bad','PATH':'bad'}):
            env=bootstrap.environment(Path('D:/disposable'))
            self.assertNotIn('PYTHONHOME',env)
            self.assertNotIn('PYTHONPATH',env)
            self.assertNotIn('bad',env['PATH'])
            self.assertEqual(env['HF_HUB_OFFLINE'],'1')


def installed_smoke(installation):
    installation=installation.resolve()
    # Explicitly limit this destructive fixture check to the repository tmp folder.
    if not installation.is_relative_to((ROOT/'tmp').resolve()):
        raise ValueError('Use a disposable installation under the repository tmp directory.')
    app=installation/'app'
    manifest=json.loads((installation/'standalone-manifest.json').read_text(encoding='utf-8'))
    for name in manifest['files']:
        if name.startswith(('app/config/','app/data/','app/workspace/','app/cache/','app/tmp/','app/runtimes/rust/')):
            raise AssertionError('Private/developer path in distribution: '+name)
    # Simulate moving from a developer machine, and poison inherited Python paths.
    for kind in ('downloader','marker','retrieval'):
        (app/'runtimes'/kind/'pyvenv.cfg').write_text('home = Z:\\missing-developer-machine\n',encoding='utf-8')
    env={**os.environ,'PYTHONHOME':'Z:\\invalid','PYTHONPATH':'Z:\\invalid',
         'SCHOLARNOTELM_ROOT':'Z:\\invalid','PATH':str(Path(os.environ['SystemRoot'])/'System32'),
         'HTTP_PROXY':'http://127.0.0.1:9','HTTPS_PROXY':'http://127.0.0.1:9','ALL_PROXY':'http://127.0.0.1:9'}
    result=subprocess.run([str(installation/'ScholarNoteLM-Standalone.exe'),'--check'],
                          cwd=ROOT/'tmp',env=env,timeout=600)
    log=(app/'tmp/standalone-check.log').read_text(encoding='utf-8')
    print(log)
    if result.returncode:raise AssertionError('Installed offline runtime check failed')
    for kind in ('downloader','marker','retrieval'):
        home=(app/'runtimes'/kind/'pyvenv.cfg').read_text(encoding='utf-8').splitlines()[0]
        assert str(app/'runtimes/python'/manifest['python']) in home
    print('Installed smoke passed with relocated homes, unrelated working directory, poisoned global Python and unavailable network proxies.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation',type=Path)
    args=parser.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PackageBoundaries))
    if not result.wasSuccessful():sys.exit(1)
    if args.installation:installed_smoke(args.installation)
