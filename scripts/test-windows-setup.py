"""Windows installer ownership, resume and relocation checks; no network calls."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('windows_setup',Path(__file__).with_name('setup-runtime-windows.py'))
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)


@unittest.skipUnless(os.name=='nt','Windows installer')
class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        (self.root/'services/downloader').mkdir(parents=True)
        (self.root/'services/downloader/engine.py').touch()
    def tearDown(self):self.temp.cleanup()
    def test_unmanaged_environment_is_preserved(self):
        (self.root/'runtimes').mkdir()
        file=self.root/'runtimes/keep';file.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'unmanaged'):setup.preflight(self.root,'lock')
        self.assertEqual(file.read_bytes(),b'keep')
    def test_resume_only_owns_matching_plan(self):
        state=setup.preflight(self.root,'lock')
        (self.root/'runtimes').mkdir();state['done']=['python']
        setup.atomic_json(self.root/'runtimes/install-state.json',state)
        self.assertEqual(setup.preflight(self.root,'lock')['done'],['python'])
        with self.assertRaisesRegex(ValueError,'differs'):setup.preflight(self.root,'other')
    def test_download_checksum_failure_preserves_existing_file(self):
        file=self.root/'cache/install/tool.zip';file.parent.mkdir(parents=True);file.write_bytes(b'wrong')
        with patch.object(setup.urllib.request,'urlopen') as network:
            with self.assertRaisesRegex(ValueError,'checksum'):setup.download(self.root,'tool.zip',{'sha256':'invalid'})
            network.assert_not_called()
        self.assertEqual(file.read_bytes(),b'wrong')
    def test_relocation_rebases_owned_venv_without_touching_packages(self):
        config=self.root/'runtimes/downloader/pyvenv.cfg';config.parent.mkdir(parents=True)
        config.write_text('home = C:\\old\\python\ninclude-system-site-packages = false\n',encoding='utf-8')
        sentinel=config.parent/'keep';sentinel.write_bytes(b'package')
        setup.repair_python_home(self.root)
        self.assertIn(str(self.root/'runtimes/python'/setup.PLAN['python']),config.read_text(encoding='utf-8'))
        self.assertIn('include-system-site-packages = false',config.read_text(encoding='utf-8'))
        self.assertEqual(sentinel.read_bytes(),b'package')
    def test_second_installer_cannot_enter(self):
        (self.root/'runtimes').mkdir()
        with setup.install_lock(self.root):
            with self.assertRaisesRegex(ValueError,'Another installer'):
                with setup.install_lock(self.root):pass


if __name__=='__main__':unittest.main()
