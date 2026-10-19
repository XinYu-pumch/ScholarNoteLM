import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'services/downloader'))
sys.path.insert(0, str(ROOT/'services/marker'))
import compute_devices as devices
from device_probe import probe
from inference_client import InferenceClient
from inference_server import accelerator_error


class ComputeTests(unittest.TestCase):
    def test_cpu_preference_does_not_probe_or_import_torch(self):
        with patch.object(devices, 'inspect_runtime') as inspect:
            self.assertEqual(devices.detect(ROOT, 'cpu')['device'], 'cpu')
            inspect.assert_not_called()

    def test_mac_auto_preserves_mps_preference(self):
        torch = Mock(__version__='fixture', version=SimpleNamespace(cuda=None))
        torch.backends.mps.is_available.return_value = True
        tensor = Mock()
        tensor.__matmul__ = Mock(return_value=tensor)
        tensor.sum.return_value.item.return_value = 512
        torch.ones.return_value = tensor
        self.assertEqual(probe(torch, platform='darwin')['device'], 'mps')
        torch.cuda.is_available.assert_not_called()

    def test_cuda_available_but_kernel_fails_uses_cpu(self):
        torch = Mock(__version__='fixture', version=SimpleNamespace(cuda='12.6'))
        torch.cuda.is_available.return_value = True
        torch.ones.side_effect = RuntimeError('no kernel image is available')
        result = probe(torch, platform='win32')
        self.assertEqual(result['device'], 'cpu')
        self.assertIn('kernel', result['reason'])

    def test_probe_timeout_and_broken_import_do_not_escape(self):
        with patch.object(devices.subprocess, 'run', side_effect=subprocess.TimeoutExpired('probe', 45)):
            self.assertTrue(devices.inspect_runtime(ROOT, 'python')['importFailed'])

    @unittest.skipUnless(sys.platform=='win32', 'Windows optional CUDA environment')
    def test_gpu_detected_without_component_is_not_reported_as_no_gpu(self):
        with patch.object(devices, 'cuda_runtime', return_value=None), \
             patch.object(devices, 'inspect_runtime', return_value={'device':'cpu', 'reason':'CPU build'}), \
             patch.object(devices, 'nvidia_inventory', return_value=[{'name':'NVIDIA fixture'}]):
            result = devices.detect(ROOT)
            self.assertIn('CUDA 加速组件', result['reason'])
            self.assertEqual(result['runtime'], str(devices.cpu_runtime(ROOT)))

    def test_runtime_pointer_cannot_escape_installation(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            root = Path(folder)
            (root/'runtimes').mkdir()
            (root/'runtimes/cuda-state.json').write_text(json.dumps({'ready':True, 'directory':'../../outside'}))
            self.assertIsNone(devices.cuda_runtime(root))

    def test_only_accelerator_errors_trigger_recovery(self):
        self.assertEqual(accelerator_error(RuntimeError('CUDA out of memory')), 'oom')
        self.assertEqual(accelerator_error(RuntimeError('CUDA error: device-side assert triggered')), 'accelerator')
        for message in ('missing model', 'invalid PDF', 'permission denied'):
            self.assertEqual(accelerator_error(RuntimeError(message)), 'conversion')

    def client_case(self, results, automatic=True):
        client = InferenceClient(ROOT, {'device':'cuda', 'runtime':'fixture', 'name':'GPU'}, automatic)
        states = []
        def request(pdf, output, workers, cancelled):
            states.append((client.selection['device'], client.batch))
            result = results.pop(0)
            if result['ok']:
                out = output/'1'; out.mkdir(); (out/'1.md').write_text('success')
                result = {**result, 'folder':str(out)}
            return result
        return client, states, request

    def test_oom_retries_small_batch_then_cpu_once(self):
        client, states, request = self.client_case([{'ok':False,'kind':'oom','error':'CUDA out of memory'}]*2+[{'ok':True}])
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder, patch.object(client, 'request', side_effect=request):
            output = client.convert(Path(folder)/'1.pdf', folder, 1, lambda:False)
            self.assertEqual((output/'1.md').read_text(), 'success')
        self.assertEqual(states, [('cuda',2), ('cuda',1), ('cpu',1)])
        self.assertEqual(len(client.fallbacks), 2)

    def test_bad_pdf_and_manual_gpu_do_not_retry(self):
        for kind, auto in [('conversion',True), ('oom',False)]:
            client, states, request = self.client_case([{'ok':False,'kind':kind,'error':'fixture error'}], auto)
            with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder, patch.object(client, 'request', side_effect=request):
                with self.assertRaisesRegex(RuntimeError,'fixture error'):
                    client.convert(Path(folder)/'1.pdf', folder, 1, lambda:False)
            self.assertEqual(len(states), 1)

    def test_cpu_failure_is_not_retried_indefinitely(self):
        client, states, request = self.client_case([{'ok':False,'kind':'accelerator','error':'CUDA error'},
                                                   {'ok':False,'kind':'oom','error':'CPU out of memory'}])
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder, patch.object(client, 'request', side_effect=request):
            with self.assertRaisesRegex(RuntimeError,'CPU out of memory'):
                client.convert(Path(folder)/'1.pdf', folder, 1, lambda:False)
        self.assertEqual(states, [('cuda',2), ('cpu',1)])

    def test_cancel_terminates_the_owned_subprocess(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            root = Path(folder)
            script = root/'services/marker/inference_server.py'; script.parent.mkdir(parents=True)
            script.write_text('import sys,time\nfor line in sys.stdin: time.sleep(60)\n')
            client = InferenceClient(root, {'device':'cuda','runtime':sys.executable})
            started = time.monotonic()
            with self.assertRaises(InterruptedError):
                client.convert(root/'1.pdf', root, 1, lambda: time.monotonic()-started>0.3)
            self.assertIsNone(client.process)
            self.assertLess(time.monotonic()-started, 5)
            self.assertFalse(list(root.glob('inference-*')))

    def test_hardware_result_does_not_change_existing_cache_signatures(self):
        import markdown_service as m
        import conversion_config as conversion
        original = dict(m.DEFAULTS)
        accelerated = {**original, 'computeDevice':'cuda', 'computePrecision':'float16'}
        self.assertEqual(m.signature(original), m.signature(accelerated))
        self.assertEqual(conversion.identity(ROOT, original), conversion.identity(ROOT, accelerated))


if __name__ == '__main__':
    unittest.main()
