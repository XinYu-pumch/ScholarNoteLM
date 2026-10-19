"""Own the GPU subprocess and retry only accelerator failures in fresh processes."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import uuid

import compute_devices


class InferenceClient:
    def __init__(self, root, selection, automatic=True, on_change=None):
        self.root = Path(root)
        self.selection = dict(selection)
        self.automatic = automatic
        self.batch = 2
        self.process = None
        self.fallbacks = []
        self.on_change = on_change or (lambda: None)
        self.selection['precision'] = 'float16' if self.selection['device']=='cuda' else 'float32'

    def close(self):
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                if os.name == 'nt':
                    # PDF text extraction can create its own children. Close this
                    # owned tree as well when cancelling a long conversion.
                    try:
                        subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'],
                                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,
                                       **compute_devices.process_options())
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            process.stdin.close()
            process.stdout.close()

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.close()
        self.replies = queue.Queue()
        self.process = subprocess.Popen([self.selection['runtime'], '-I', str(self.root/'services/marker/inference_server.py'),
                         '--device', self.selection['device'], '--batch', str(self.batch), '--parent', str(os.getpid())],
                         cwd=self.root, env=compute_devices.environment(self.root), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True, encoding='utf-8', **compute_devices.process_options())
        stream, replies = self.process.stdout, self.replies
        def read():
            try:
                for line in stream:
                    replies.put(json.loads(line))
            except (ValueError, OSError) as exc:
                replies.put({'ok': False, 'kind': 'protocol', 'error': str(exc)})
            finally:
                replies.put({'ok': False, 'kind': 'crash', 'error': 'Inference process exited unexpectedly'})
        threading.Thread(target=read, daemon=True).start()

    def request(self, pdf, output, workers, cancelled):
        self.start()
        try:
            self.process.stdin.write(json.dumps({'pdf': str(pdf), 'output': str(output), 'workers': workers})+'\n')
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            return {'ok': False, 'kind': 'crash', 'error': 'Inference process exited unexpectedly'}
        started = time.monotonic()
        while True:
            if cancelled():
                self.close()
                raise InterruptedError('转换已停止，结果未发布')
            if time.monotonic()-started > 3600:
                self.close()
                raise RuntimeError('单篇转换超过一小时，已停止推理进程')
            try:
                return self.replies.get(timeout=0.2)
            except queue.Empty:
                continue

    def convert(self, pdf, stage, workers, cancelled):
        # OOM gets at most one smaller GPU attempt, followed by at most one CPU attempt.
        while True:
            output = Path(stage)/('inference-'+uuid.uuid4().hex)
            output.mkdir()
            try:
                result = self.request(pdf, output, workers, cancelled)
                if result['ok']:
                    source = Path(result['folder']).resolve()
                    if not source.is_relative_to(output.resolve()):
                        raise ValueError('Inference output escaped staging directory')
                    destination = Path(stage)/Path(pdf).stem
                    shutil.move(str(source), str(destination))
                    return destination
            finally:
                shutil.rmtree(output)
            self.close()
            if not self.automatic or self.selection['device'] != 'cuda' or result['kind'] not in ('oom', 'accelerator', 'crash'):
                raise RuntimeError(result['error'])
            self.fallbacks.append({'device': 'cuda', 'kind': result['kind'], 'reason': result['error']})
            if result['kind'] == 'oom' and self.batch > 1:
                self.batch = 1
            else:
                self.selection.update(device='cpu', name='CPU', runtime=str(compute_devices.cpu_runtime(self.root)), reason=result['error'], precision='float32')
                self.batch = 1
            self.on_change()
