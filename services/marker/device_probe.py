"""Small isolated accelerator check. Does not load models or access user data."""
import argparse
import json
import sys


def probe(torch, preference='auto', platform=None):
    platform = platform or sys.platform
    result = {'device': 'cpu', 'name': 'CPU', 'available': ['cpu'], 'reason': '',
              'torch': torch.__version__, 'cudaVersion': torch.version.cuda}
    candidates = (['mps'] if platform == 'darwin' else ['cuda']) if preference == 'auto' else [preference]
    for device in candidates:
        if device == 'cpu':
            return result
        try:
            if device == 'cuda':
                if not torch.version.cuda:
                    result['reason'] = '尚未安装 CUDA 加速组件'
                    continue
                if not torch.cuda.is_available():
                    result['reason'] = 'CUDA 不可用，请检查 NVIDIA 驱动和显卡'
                    continue
                # Availability alone does not check whether this GPU has usable kernels.
                x = torch.ones((32, 32), device='cuda', dtype=torch.float16)
                assert float((x @ x).sum().item()) == 32768
                torch.cuda.synchronize()
                result.update(device='cuda', name=torch.cuda.get_device_name(0),
                              memoryBytes=torch.cuda.get_device_properties(0).total_memory)
                del x
                torch.cuda.empty_cache()
            elif device == 'mps':
                if not torch.backends.mps.is_available():
                    result['reason'] = 'Apple MPS 不可用'
                    continue
                x = torch.ones((8, 8), device='mps')
                assert float((x @ x).sum().item()) == 512
                del x
                result.update(device='mps', name='Apple MPS')
            else:
                raise ValueError('Unknown device')
            result['available'].append(device)
            result['reason'] = ''
            return result
        except Exception as exc:
            result.update(device='cpu', name='CPU', reason=str(exc)[:1000])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', choices=('auto', 'cpu', 'mps', 'cuda'), default='auto')
    args = parser.parse_args()
    try:
        import torch
        result = probe(torch, args.device)
    except Exception as exc:
        result = {'device': 'cpu', 'name': 'CPU', 'available': ['cpu'], 'reason': str(exc)[:1000], 'importFailed': True}
    print(json.dumps(result, ensure_ascii=True))
