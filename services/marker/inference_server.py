"""Persistent Windows inference subprocess; stdout is a JSON-lines protocol."""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import socket
import sys
import traceback
import threading


def watch_parent(pid):
    """Close the GPU context even if the durable worker is forcibly terminated."""
    if os.name != 'nt':
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        raise RuntimeError('Cannot watch inference owner')
    def wait():
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
        os._exit(1)
    threading.Thread(target=wait, daemon=True).start()


def accelerator_error(error):
    message = str(error).lower()
    oom = 'out of memory' in message
    device_error = any(s in message for s in ('cuda error', 'cuda driver', 'cuda-capable', 'cudnn', 'cublas',
                                              'no kernel image', 'device-side assert', 'not compiled with cuda'))
    return 'oom' if oom else 'accelerator' if device_error else 'conversion'


def serve(device, batch):
    root = Path(os.environ['SCHOLARNOTELM_ROOT'])
    sys.path.insert(0, str(root/'services/marker/vendor'))
    os.environ.update(TORCH_DEVICE=device, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HOME=str(root/'cache/huggingface'), TORCH_HOME=str(root/'cache/torch'),
                      XDG_CACHE_HOME=str(root/'cache'), SURYA_CACHE_DIR=str(root/'models/marker'),
                      TOKENIZERS_PARALLELISM='false', TQDM_DISABLE='1')
    connect = socket.socket.connect
    def offline(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise RuntimeError('Local conversion cannot access the network')
        return connect(sock, address)
    socket.socket.connect = offline
    models = None
    for line in sys.stdin:
        request = json.loads(line)
        try:
            with redirect_stdout(sys.stderr):
                import torch
                from marker.models import create_model_dict
                from marker.config.parser import ConfigParser
                from marker.output import save_output
                if models is None:
                    models = create_model_dict(device=device, dtype=torch.float16 if device == 'cuda' else torch.float32)
                    for predictor in models.values():
                        predictor.batch_size = batch
                parser = ConfigParser({'output_dir': request['output'], 'output_format': 'markdown',
                                       'disable_ocr': True, 'pdftext_workers': request['workers'],
                                       'disable_tqdm': True, 'use_llm': False})
                converter = parser.get_converter_cls()(config=parser.generate_config_dict(), artifact_dict=models,
                            processor_list=parser.get_processors(), renderer=parser.get_renderer(), llm_service=None)
                with torch.inference_mode():
                    rendered = converter(request['pdf'])
                folder = parser.get_output_folder(request['pdf'])
                save_output(rendered, folder, Path(request['pdf']).stem)
                result = {'ok': True, 'folder': str(folder), 'device': device, 'precision': 'float16' if device == 'cuda' else 'float32'}
                del rendered, converter
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            result = {'ok': False, 'kind': accelerator_error(exc), 'error': str(exc)[:3000]}
        print(json.dumps(result), flush=True)
        if not result['ok'] and result['kind'] in ('oom', 'accelerator'):
            return  # Never reuse a failed CUDA context.


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', choices=('cuda', 'cpu'), required=True)
    parser.add_argument('--batch', type=int, default=2)
    parser.add_argument('--parent', type=int, required=True)
    args = parser.parse_args()
    watch_parent(args.parent)
    serve(args.device, args.batch)
