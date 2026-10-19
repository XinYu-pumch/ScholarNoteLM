"""Accelerator discovery runs in a private interpreter, never in the RPC process."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def environment(root):
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONHOME', 'PYTHONPATH', 'TORCH_DEVICE')}
    env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', SCHOLARNOTELM_ROOT=str(root),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTORCH_ENABLE_MPS_FALLBACK='1')
    return env


def cpu_runtime(root):
    return Path(root)/('runtimes/marker/Scripts/python.exe' if os.name == 'nt' else 'runtimes/marker/bin/python')


def cuda_runtime(root):
    try:
        root = Path(root).resolve()
        state = json.loads((root/'runtimes/cuda-state.json').read_text(encoding='utf-8'))
        runtime_root = (root/'runtimes').resolve()
        folder = (runtime_root/state['directory']).resolve()
        if folder.parent != runtime_root or not folder.name.startswith('marker-cu'):
            return None
        python = folder/'Scripts/python.exe'
        return python if python.is_file() and state.get('ready') else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def nvidia_inventory():
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,compute_cap', '--format=csv,noheader'],
                                capture_output=True, text=True, timeout=8, **process_options())
        if result.returncode:
            return []
        return [{'name': row[0].strip(), 'driver': row[1].strip(), 'capability': row[2].strip()}
                for row in csv.reader(io.StringIO(result.stdout)) if len(row) == 3]
    except (OSError, subprocess.TimeoutExpired):
        return []


def inspect_runtime(root, python, preference='auto'):
    try:
        process = subprocess.run([str(python), '-I', str(Path(root)/'services/marker/device_probe.py'), '--device', preference],
                                 cwd=root, env=environment(root), capture_output=True, text=True, encoding='utf-8',
                                 timeout=45, **process_options())
        if process.returncode:
            raise RuntimeError('Accelerator check exited with code '+str(process.returncode))
        result = json.loads(process.stdout.strip().splitlines()[-1])
        result['runtime'] = str(python)
        return result
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return {'device': 'cpu', 'name': 'CPU', 'available': ['cpu'], 'reason': str(exc)[:1000], 'importFailed': True}


def detect(root, preference='auto'):
    root = Path(root)
    baseline = cpu_runtime(root)
    if preference == 'cpu':
        return {'device': 'cpu', 'name': 'CPU', 'available': ['cpu'], 'reason': '', 'runtime': str(baseline)}
    cuda = cuda_runtime(root) if os.name == 'nt' and preference in ('auto', 'cuda') else None
    result = inspect_runtime(root, cuda or baseline, preference)
    if result['device'] == 'cpu':
        result['runtime'] = str(baseline)
        if os.name == 'nt':
            result['gpus'] = nvidia_inventory()
            if result['gpus'] and not cuda:
                result['reason'] = '已检测到 NVIDIA 显卡，请通过环境安装程序安装 CUDA 加速组件'
    result['checkedAt'] = time.time()
    return result


def cached(root):
    try:
        return json.loads((Path(root)/'cache/compute-device.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
