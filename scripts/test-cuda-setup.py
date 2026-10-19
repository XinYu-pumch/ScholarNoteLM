"""CUDA profile selection and installer isolation; no downloads."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cuda_setup', Path(__file__).with_name('setup-cuda-windows.py'))
setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)
profiles = json.loads((setup.ROOT/'scripts/install/cuda-windows-x64.json').read_text())['profiles']


class CudaSetupTests(unittest.TestCase):
    def test_profile_matches_architecture_and_driver(self):
        self.assertEqual(setup.choose_profile([{'capability':'8.9','driver':'591.74'}], profiles), 'cu126')
        self.assertEqual(setup.choose_profile([{'capability':'12.0','driver':'591.74'}], profiles), 'cu128')
        self.assertIsNone(setup.choose_profile([{'capability':'8.9','driver':'527.0'}], profiles))
        self.assertIsNone(setup.choose_profile([], profiles))

    def test_no_gpu_does_not_touch_existing_environment(self):
        with patch.object(setup.compute_devices, 'nvidia_inventory', return_value=[]), \
             patch.object(setup.setup, 'run') as run:
            self.assertIsNone(setup.install_cuda(setup.ROOT, Path('unused')))
            run.assert_not_called()

    def test_failed_validation_never_publishes_or_changes_cpu(self):
        with tempfile.TemporaryDirectory(dir=setup.ROOT/'tmp') as folder:
            root=Path(folder)
            (root/'scripts/install').mkdir(parents=True)
            (root/'scripts/install/cuda-windows-x64.json').write_text(json.dumps({'profiles':profiles}))
            (root/'runtimes/marker').mkdir(parents=True)
            sentinel=root/'runtimes/marker/keep'; sentinel.write_text('CPU unchanged')
            (root/'runtimes/install-state.json').write_text(json.dumps({'platform':'windows-x64','fingerprint':'test','done':['python']}))
            pointer=root/'runtimes/cuda-state.json';pointer.write_text('{"ready":false,"existing":"retained"}')
            def fake_run(root,*args):
                if 'venv' in args:
                    target=Path(args[-1]);(target/'Lib/site-packages').mkdir(parents=True)
                    (target/'pyvenv.cfg').touch()
            with patch.object(setup.setup,'fingerprint',return_value='test'), \
                 patch.object(setup.setup,'run',side_effect=fake_run), \
                 patch.object(setup.compute_devices,'inspect_runtime',return_value={'device':'cpu','reason':'driver error'}):
                with self.assertRaisesRegex(ValueError,'validation failed'):
                    setup.install_cuda(root,Path('unused'),'cu126')
            self.assertEqual(json.loads(pointer.read_text()), {'ready':False,'existing':'retained'})
            self.assertEqual(sentinel.read_text(), 'CPU unchanged')


if __name__ == '__main__':unittest.main()
