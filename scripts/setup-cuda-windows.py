"""Optional, hash-locked CUDA overlay. The existing CPU and macOS environments stay intact."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'services/downloader'))
import compute_devices

spec = importlib.util.spec_from_file_location('windows_setup', ROOT/'scripts/setup-runtime-windows.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def version(value):
    return tuple(int(part) for part in value.split('.'))


def choose_profile(gpus, profiles):
    # Start conservatively: a supported CUDA wheel and its full toolkit-era driver floor.
    # Older drivers may offer minor-version compatibility, but are not promised here.
    if not gpus:
        return None
    gpu = gpus[0]
    try:
        capability = float(gpu['capability'])
        profile = 'cu128' if capability >= 10 else 'cu126'
        if capability < 5 or version(gpu['driver']) < version(profiles[profile]['minimumWindowsDriver']):
            return None
        return profile
    except (ValueError, KeyError):
        return None


def install_cuda(root, uv, requested='auto'):
    if os.name != 'nt':
        raise ValueError('CUDA overlay is for Windows x64 only; macOS keeps its MPS environment.')
    plan = json.loads((root/'scripts/install/cuda-windows-x64.json').read_text(encoding='utf-8'))
    profile = choose_profile(compute_devices.nvidia_inventory(), plan['profiles']) if requested == 'auto' else requested
    if not profile:
        print('CUDA: no supported GPU/driver detected. CPU environment remains available.', flush=True)
        return None
    if profile not in plan['profiles']:
        raise ValueError('Unsupported CUDA profile')
    state_path = root/'runtimes/install-state.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    if state.get('platform') != 'windows-x64' or state.get('fingerprint') != setup.fingerprint(root) or 'python' not in state.get('done', []):
        raise ValueError('Install the matching managed CPU environment first.')
    item = plan['profiles'][profile]
    signature = hashlib.sha256((setup.fingerprint(root)+json.dumps(item, sort_keys=True)).encode()).hexdigest()
    directory = 'marker-'+profile+'-'+signature[:12]
    target = root/'runtimes'/directory
    python = target/'Scripts/python.exe'
    pointer = root/'runtimes/cuda-state.json'
    with setup.install_lock(root):
        if pointer.is_file():
            previous = json.loads(pointer.read_text(encoding='utf-8'))
            if previous.get('fingerprint') == signature and previous.get('ready') and python.is_file():
                result = compute_devices.inspect_runtime(root, python, 'cuda')
                if result['device'] != 'cuda':
                    raise ValueError('Installed CUDA check failed: '+result.get('reason', ''))
                print('CUDA already installed:', result['name'], flush=True)
                return result
        if target.resolve() != target:
            raise ValueError('Refusing linked CUDA environment')
        ownership = target/'cuda-install.json'
        if target.exists():
            if not ownership.is_file() or json.loads(ownership.read_text(encoding='utf-8')).get('fingerprint') != signature:
                raise ValueError('Unmanaged CUDA directory; refusing overwrite')
        else:
            target.mkdir()
            setup.atomic_json(ownership, {'fingerprint': signature})
        base = root/'runtimes/python'/setup.PLAN['python']/'python.exe'
        if not (target/'pyvenv.cfg').is_file():
            setup.run(root, uv, 'venv', '--allow-existing', '--python', base, target)
        # Private torch takes precedence; all other exact-locked dependencies are shared
        # with the owned CPU runtime. No global site-packages or system Python is used.
        lock = target/'torch.lock'
        lock.write_text('torch @ '+item['url']+' \\\n    --hash=sha256:'+item['sha256']+'\n', encoding='utf-8')
        print('Installing optional CUDA:', profile, '(large download; CPU is unchanged)', flush=True)
        setup.run(root, uv, 'pip', 'install', '--python', python, '--no-deps', '--require-hashes', '-r', lock)
        (target/'Lib/site-packages/scholarnotelm-base.pth').write_text('../../../marker/Lib/site-packages\n', encoding='utf-8')
        setup.run(root, python, '-I', '-c',
                  "import torch,transformers,surya; assert torch.__version__=='2.9.1+"+profile+"'; assert transformers.__version__=='4.49.0'; print('CUDA imports OK')")
        result = compute_devices.inspect_runtime(root, python, 'cuda')
        if result['device'] != 'cuda':
            raise ValueError('CUDA validation failed; CPU retained: '+result.get('reason', ''))
        setup.atomic_json(pointer, {'schemaVersion': 1, 'ready': True, 'directory': directory,
                                  'profile': profile, 'fingerprint': signature})
        print('CUDA ready:', result['name'], flush=True)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--uv', type=Path, default=ROOT/'cache/bootstrap/uv/uv.exe')
    parser.add_argument('--profile', choices=('auto', 'cu126', 'cu128'), default='auto')
    args = parser.parse_args()
    try:
        install_cuda(args.root.resolve(), args.uv, args.profile)
    except Exception as exc:
        print('CUDA setup stopped; CPU environment was retained:', exc, file=sys.stderr)
        sys.exit(1)
