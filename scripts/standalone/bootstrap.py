"""Offline preparation for the standalone edition; no pip, network or global Python.

Executed by the bundled *base* Python with -I -S, before using any venv.
Only generated runtime configuration and empty writable directories are changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


def reject_links(path):
    # resolve()!=absolute() also flags harmless Windows 8.3 directory aliases.
    # Test actual reparse points instead, including parents of a not-yet-created file.
    for entry in (path, *path.parents):
        if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
            raise ValueError('Linked package paths are not supported: ' + str(path))


def safe_path(root, name):
    part = PurePosixPath(name)
    if (not name or part.is_absolute() or '..' in part.parts or '\\' in name
            or ':' in name or str(part) != name):
        raise ValueError('Invalid package path: ' + name)
    path = root.joinpath(*part.parts)
    reject_links(path)
    return path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def environment(root):
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV'):
        env.pop(key, None)
    windows = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env.update(SCHOLARNOTELM_ROOT=str(root), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', PLAYWRIGHT_BROWSERS_PATH=str(root/'runtimes/playwright'),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HOME=str(root/'cache/huggingface'), TORCH_HOME=str(root/'cache/torch'),
               TMP=str(root/'tmp'), TEMP=str(root/'tmp'), TMPDIR=str(root/'tmp'),
               PATH=os.pathsep.join([str(root/'runtimes/node'), str(windows/'System32'),
                                    str(windows), str(windows/'System32/WindowsPowerShell/v1.0')]))
    return env


def prepare(root):
    reject_links(root)
    root = root.resolve()
    bundle = root.parent
    metadata = json.loads((bundle/'standalone-manifest.json').read_text(encoding='utf-8'))
    if metadata.get('schemaVersion') != 1 or metadata.get('platform') != 'windows-x64':
        raise ValueError('Unsupported standalone manifest')
    base = safe_path(root, 'runtimes/python/' + metadata['python'])
    if not (base/'python.exe').is_file():
        raise ValueError('Bundled base Python is missing; reinstall this package.')
    for name in ('config', 'data', 'cache', 'tmp'):
        safe_path(root, name).mkdir(parents=True, exist_ok=True)
    for kind in ('downloader', 'marker', 'retrieval'):
        directory = safe_path(root, 'runtimes/' + kind)
        if not (directory/'Scripts/python.exe').is_file():
            raise ValueError('Bundled runtime missing: ' + kind)
        content = (f'home = {base}\nimplementation = CPython\nversion_info = 3.12.9\n'
                   'include-system-site-packages = false\n')
        config = safe_path(root, 'runtimes/' + kind + '/pyvenv.cfg')
        if not config.exists() or config.read_text(encoding='utf-8') != content:
            temporary = config.with_suffix('.standalone-tmp')
            temporary.write_text(content, encoding='utf-8')
            os.replace(temporary, config)
    # Only test isolated prefixes here. Heavy imports/hash checks are an explicit --check.
    for kind in ('downloader', 'marker', 'retrieval'):
        code = ('import sys;from pathlib import Path;'
                f'assert Path(sys.prefix).resolve()==Path({str(root/"runtimes"/kind)!r}).resolve();'
                f'assert Path(sys.base_prefix).resolve()==Path({str(base)!r}).resolve()')
        subprocess.run([str(root/'runtimes'/kind/'Scripts/python.exe'), '-I', '-c', code],
                       cwd=root, env=environment(root), check=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    print('Standalone paths prepared; no network or system Python used.', flush=True)
    return metadata


def verify(root, metadata):
    bundle = root.parent
    for name, record in metadata['files'].items():
        path = safe_path(bundle, name)
        if not path.is_file() or path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError('Package damaged or changed: ' + name)
    # The original application source-pairing remains enforced, unchanged.
    original = json.loads((root/'source-manifest.json').read_text(encoding='utf-8'))
    for name, expected in original['files'].items():
        if sha(safe_path(root, name)) != expected:
            raise ValueError('Application/source mismatch: ' + name)
    env = environment(root)
    common = "import httpx,pypdf,bs4,lxml,docx,markdown,markdown_it;print('Downloader imports OK')"
    marker = ("import sys;from pathlib import Path;sys.path.insert(0,str(Path.cwd()/'services/marker/vendor'));"
              "import torch,numpy,transformers,surya;from marker.models import create_model_dict;"
              "assert not torch.cuda.is_available();print('CPU Marker imports OK')")
    for kind, code in (('downloader', common), ('marker', marker), ('retrieval', 'import httpx,numpy,torch;print("Retrieval imports OK")')):
        subprocess.run([str(root/'runtimes'/kind/'Scripts/python.exe'), '-I', '-c', code],
                       cwd=root, env=env, check=True, timeout=120,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    code = ("import {createRequire} from 'node:module';"
            "const r=createRequire(process.cwd()+'/services/downloader/scihub_browser.mjs');"
            "const {chromium}=r('@playwright/test');"
            "const b=await chromium.launch({headless:true});"
            "const p=await b.newPage();await p.setContent('<title>Offline check</title>');"
            "if(await p.title()!=='Offline check')throw Error('Browser failed');"
            "await b.close();console.log('Bundled Chromium offline check OK');")
    subprocess.run([str(root/'runtimes/node/node.exe'), '--input-type=module', '-e', code],
                   cwd=root, env=env, check=True, timeout=120,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    print(f'Verified {len(metadata["files"])} packaged files and all runtime imports.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = args.root.absolute()
    metadata = prepare(root)
    if args.check:
        verify(root, metadata)


if __name__ == '__main__':
    main()
