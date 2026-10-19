"""Immutable Mac app resources, writable per-user state; no installation/network."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

STATE_NAME = '.scholarnotelm-standalone.json'


def environment(root):
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV'):
        env.pop(key, None)
    env.update(SCHOLARNOTELM_ROOT=str(root), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', PLAYWRIGHT_BROWSERS_PATH=str(root/'runtimes/playwright'),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HOME=str(root/'cache/huggingface'), TORCH_HOME=str(root/'cache/torch'),
               TMPDIR=str(root/'tmp'), TMP=str(root/'tmp'), TEMP=str(root/'tmp'),
               PATH=str(root/'runtimes/node/bin')+':/usr/bin:/bin:/usr/sbin:/sbin')
    return env


def prepare(bundle, root):
    payload = bundle/'Contents/Resources/payload'
    metadata = json.loads((bundle/'Contents/Resources/standalone-manifest.json').read_text())
    if metadata.get('schemaVersion') != 1 or metadata.get('platform') != 'macos-arm64':
        raise ValueError('Unsupported standalone package.')
    marker = root/STATE_NAME
    if root.is_symlink():
        raise ValueError('The standalone state folder cannot be a symbolic link.')
    root.mkdir(parents=True, exist_ok=True)
    # Never repurpose a source installation or an arbitrary populated folder.
    if not marker.exists() and any(p.name != '.launcher.lock' for p in root.iterdir()):
        raise ValueError('Standalone state folder is not empty and is not owned by this edition.')
    old = json.loads(marker.read_text()) if marker.exists() else {'schemaVersion': 1, 'links': []}
    if old.get('schemaVersion') != 1:
        raise ValueError('Unsupported standalone state version.')
    links = sorted(p.name for p in payload.iterdir())
    reserved = {'config', 'data', 'cache', 'tmp', 'workspace', STATE_NAME, '.launcher.lock'}
    if reserved.intersection(links):
        raise ValueError('Private or writable directory included in the app payload.')
    # Check every destination before changing any link. Existing real files are never removed.
    for name in set(old['links']) | set(links):
        if Path(name).name != name or name in reserved:
            raise ValueError('Invalid standalone link record.')
        target = root/name
        if target.exists() and not target.is_symlink():
            raise ValueError('Refusing to overwrite standalone resources: '+name)
    for name in set(old['links']) - set(links):
        (root/name).unlink(missing_ok=True)
    for name in links:
        target = root/name
        if target.is_symlink() and os.readlink(target) == str(payload/name):
            continue
        temporary = root/('.resource-'+name)
        if temporary.exists() or temporary.is_symlink():
            raise ValueError('Incomplete resource relocation: '+name)
        temporary.symlink_to(payload/name, target_is_directory=(payload/name).is_dir())
        os.replace(temporary, target)
    for name in ('config', 'data', 'cache', 'tmp'):
        if (root/name).is_symlink():
            raise ValueError('Writable state directories cannot be symbolic links.')
        (root/name).mkdir(exist_ok=True)
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'schemaVersion': 1, 'links': links, 'bundle': str(bundle)}))
    os.replace(temporary, marker)
    return metadata


def verify(bundle, root, metadata):
    payload = bundle/'Contents/Resources/payload'
    for name, expected in metadata['files'].items():
        part = Path(name)
        if part.is_absolute() or '..' in part.parts:
            raise ValueError('Invalid manifest path.')
        path = payload/part
        if 'link' in expected:
            if not path.is_symlink() or os.readlink(path) != expected['link']:
                raise ValueError('Changed resource link: '+name)
        else:
            if not path.is_file() or path.is_symlink():
                raise ValueError('Missing resource: '+name)
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if path.stat().st_size != expected['bytes'] or actual != expected['sha256']:
                raise ValueError('Changed resource: '+name)
    env = environment(root)
    checks = {
        'downloader': 'import httpx,pypdf,bs4,lxml,docx,markdown,markdown_it',
        'marker': 'import torch,numpy,transformers,surya;from marker.models import create_model_dict',
        'retrieval': 'import httpx,numpy,torch',
    }
    for kind, imports in checks.items():
        code = ('import sys;from pathlib import Path;'
                'sys.path.insert(0,str(Path.cwd()/"services/marker/vendor"));'
                f'assert Path(sys.prefix).resolve()==(Path.cwd()/"runtimes/{kind}").resolve();'
                'assert Path(sys.base_prefix).resolve().is_relative_to((Path.cwd()/"runtimes/python").resolve());'
                + imports + ';print("' + kind + ' imports OK")')
        subprocess.run([str(root/'runtimes'/kind/'bin/python'), '-I', '-B', '-c', code],
                       cwd=root, env=env, check=True, timeout=120)
    code = ("import {createRequire} from 'node:module';"
            "const r=createRequire(process.cwd()+'/services/downloader/scihub_browser.mjs');"
            "const {chromium}=r('@playwright/test');const b=await chromium.launch({headless:true});"
            "const p=await b.newPage();await p.setContent('<title>Offline check</title>');"
            "if(await p.title()!=='Offline check')throw Error('Browser check failed');await b.close();")
    subprocess.run([str(root/'runtimes/node/bin/node'), '--input-type=module', '-e', code],
                   cwd=root, env=env, check=True, timeout=120)
    print(f'Verified {len(metadata["files"])} resources, offline runtimes, models and Chromium.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    root = Path(os.environ.get('SCHOLARNOTELM_STANDALONE_HOME',
                str(Path.home()/'Library/Application Support/ScholarNoteLM-Standalone'))).expanduser().absolute()
    if root.is_symlink() or root.is_relative_to(bundle):
        raise ValueError('State must be outside the immutable app bundle.')
    root.mkdir(parents=True, exist_ok=True)
    with (root/'.launcher.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('ScholarNoteLM Standalone is already running for this user.') from None
        metadata = prepare(bundle, root)
        if args.check:
            verify(bundle, root, metadata)
        elif not args.prepare_only:
            return subprocess.call([str(bundle/'Contents/MacOS/scholarnotelm-core')],
                                   cwd=root, env=environment(root))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('ScholarNoteLM standalone: '+str(error), file=sys.stderr)
        if '--check' not in sys.argv and '--prepare-only' not in sys.argv:
            subprocess.run(['/usr/bin/osascript', '-e',
                'on run argv\ndisplay alert "ScholarNoteLM" message (item 1 of argv) as critical\nend run',
                '--', str(error)], check=False)
        sys.exit(1)
