"""Provision a clean macOS arm64 checkout without BADR. Preview unless --apply."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

from install_assets import destination, digest, install, manifest, matches

SOURCE = Path(__file__).resolve().parents[1]
PYTHON = 'cpython-3.12.9-macos-aarch64-none'
NODE = {
    'path': 'node-v20.19.0-darwin-arm64.tar.gz',
    'url': 'https://nodejs.org/dist/v20.19.0/node-v20.19.0-darwin-arm64.tar.gz',
    'sha256': 'c016cd1975a264a29dc1b07c6fbe60d5df0a0c2beb4113c0450e3d998d1a0d9c',
}
RUSTUP = {
    'url': 'https://static.rust-lang.org/rustup/archive/1.28.2/aarch64-apple-darwin/rustup-init',
    'sha256': '20ef5516c31b1ac2290084199ba77dbbcaa1406c45c1d978ca68558ef5964ef5',
}
RUST = '1.98.1'


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)


def environment(root):
    env = {**os.environ, 'UV_CACHE_DIR': str(root / 'cache/uv'),
            'UV_PYTHON_INSTALL_DIR': str(root / 'runtimes/python'),
            'UV_PYTHON_BIN_DIR': str(root / 'runtimes/python/bin'),
            'UV_LINK_MODE': 'copy', 'UV_NO_CONFIG': '1',
            'CARGO_HOME': str(root / 'cache/cargo'), 'RUSTUP_HOME': str(root / 'runtimes/rust'),
            'CARGO_TARGET_DIR': str(root / 'cache/tauri-target'),
            'npm_config_cache': str(root / 'cache/npm'),
            'PLAYWRIGHT_BROWSERS_PATH': str(root / 'runtimes/playwright'),
            'TMPDIR': str(root / 'tmp'), 'TEMP': str(root / 'tmp'), 'TMP': str(root / 'tmp'),
            'SCHOLARNOTELM_ROOT': str(root), 'PYTHONDONTWRITEBYTECODE': '1',
            'PATH': str(root / 'runtimes/node/bin') + os.pathsep + os.environ.get('PATH', '')}
    # uv/npm/rustup do not all read macOS system proxy settings. Scope these
    # variables to the installer children; never write them to shell/app config.
    proxies = urllib.request.getproxies()
    for scheme in ('http', 'https'):
        if proxies.get(scheme) and not (env.get(scheme + '_proxy') or env.get(scheme.upper() + '_PROXY')):
            env[scheme.upper() + '_PROXY'] = proxies[scheme]
    env.setdefault('NO_PROXY', proxies.get('no') or 'localhost,127.0.0.1,::1')
    return env


def run(root, *args):
    subprocess.run([str(x) for x in args], cwd=root, env=environment(root), check=True)


def preflight(root, fingerprint):
    if sys.platform != 'darwin' or platform.machine().lower() not in ('arm64', 'aarch64'):
        raise ValueError('This verified lock supports macOS Apple Silicon only; other platforms require separate locks and validation.')
    if not (root / 'services/downloader/engine.py').is_file():
        raise ValueError('Target must be a source checkout, not an empty or research directory')
    for name in ['runtimes', 'models', 'cache', 'tmp', 'node_modules']:
        if (root / name).resolve() != root / name:
            raise ValueError(f'Refusing linked installation directory: {name}')
    if int(platform.mac_ver()[0].split('.')[0] or 0) < 14:
        raise ValueError('macOS 14 or later is required.')
    state_path = root / 'runtimes/install-state.json'
    state = json.loads(state_path.read_text()) if state_path.is_file() else None
    if state:
        if state.get('schemaVersion') != 1 or state.get('fingerprint') != fingerprint:
            raise ValueError('Installed manifest differs. Use a new checkout; no in-place runtime upgrades.')
    elif any((root / name).exists() for name in ['runtimes', 'node_modules', 'cache/cargo']):
        raise ValueError('Existing unmanaged environment detected. Nothing changed. Use a clean checkout; do not run this installer over the working app.')
    return state or {'schemaVersion': 1, 'fingerprint': fingerprint, 'done': []}


def locked_download(url, sha, path):
    if path.exists():
        if digest(path) == sha:
            return
        raise ValueError('Existing installer archive has an unexpected checksum')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.download-')
    try:
        with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(url, timeout=120) as response:
            shutil.copyfileobj(response, out)
        if digest(temp) != sha:
            raise ValueError('Installer download checksum mismatch')
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def install_node(root):
    archive = root / 'cache/install' / NODE['path']
    locked_download(NODE['url'], NODE['sha256'], archive)
    target = root / 'runtimes/node'
    with tempfile.TemporaryDirectory(dir=root / 'tmp', prefix='node-') as temporary:
        with tarfile.open(archive) as bundle:
            bundle.extractall(temporary, filter='data')
        extracted = Path(temporary) / 'node-v20.19.0-darwin-arm64'
        if target.exists():
            # Recover a crash between atomic publication and updating the stage log.
            expected = sorted(p.relative_to(extracted) for p in extracted.rglob('*') if p.is_file())
            actual = sorted(p.relative_to(target) for p in target.rglob('*') if p.is_file())
            if actual != expected or any(digest(target / p) != digest(extracted / p) for p in expected):
                raise ValueError('Node target differs from the locked archive; refusing overwrite')
            return
        os.replace(extracted, target)


def install_python(root, uv):
    run(root, uv, 'python', 'install', PYTHON)
    python = root / 'runtimes/python' / PYTHON / 'bin/python3.12'
    for name in ['downloader', 'marker', 'retrieval']:
        target = root / 'runtimes' / name
        if not (target / 'pyvenv.cfg').exists():
            run(root, uv, 'venv', '--relocatable', '--python', python, target)
        if name != 'retrieval':
            run(root, uv, 'pip', 'sync', '--python', target / 'bin/python', '--require-hashes',
                '--only-binary', ':all:', root / f'scripts/install/{name}-macos-arm64.lock')
    # Relative site-directory reference; never embed the developer's home folder.
    site = root / 'runtimes/retrieval/lib/python3.12/site-packages'
    site.mkdir(parents=True, exist_ok=True)
    shared = root / 'runtimes/marker/lib/python3.12/site-packages'
    (site / 'scholarnotelm-shared.pth').write_text(os.path.relpath(shared, site) + '\n')
    # uv's relocatable scripts still need their managed interpreter shipped alongside.
    for name in ['downloader', 'marker', 'retrieval']:
        for link in (root / 'runtimes' / name / 'bin').glob('python*'):
            if link.is_symlink() and Path(os.readlink(link)).is_absolute():
                target = link.resolve()
                if not target.is_relative_to(root / 'runtimes/python'):
                    raise ValueError('Interpreter escaped the managed runtime')
                link.unlink()
                link.symlink_to(os.path.relpath(target, link.parent))
        # CPython follows the interpreter link to discover its standard library
        # when home is absent. uv 0.6.6 otherwise retains an absolute home even
        # with --relocatable, which breaks after moving the whole installation.
        config = root / 'runtimes' / name / 'pyvenv.cfg'
        config.write_text(''.join(line for line in config.read_text().splitlines(keepends=True)
                                  if not line.startswith('home = ')))


def verify(root, require_models=True):
    for name in ['downloader', 'marker', 'retrieval']:
        prefix = ("import sys; from pathlib import Path; "
                  f"assert Path(sys.prefix).resolve() == (Path.cwd()/'runtimes/{name}').resolve(); "
                  "assert Path(sys.base_prefix).resolve().is_relative_to(Path.cwd()/'runtimes/python'); ")
        code = "import httpx, pypdf, bs4, lxml, docx, markdown, markdown_it; print('base imports OK')"
        if name != 'downloader':
            code = ("import sys; from pathlib import Path; "
                    "sys.path.insert(0, str(Path.cwd()/'services/marker/vendor')); "
                    "from marker.config.parser import ConfigParser; from marker.models import create_model_dict; "
                    "import marker.models, numpy, torch, surya, transformers; "
                    "assert Path(marker.models.__file__).resolve().is_relative_to(Path.cwd()/'services/marker/vendor'); "
                    "assert transformers.__version__ == '4.49.0'; print('Marker/vector imports OK')")
        run(root, root / 'runtimes' / name / 'bin/python', '-c', prefix + code)
    missing = [item['path'] for item in manifest(root) if not matches(destination(root,item['path']),item)]
    if missing and require_models:
        raise ValueError('请从网盘取得匹配的 models 文件夹并放入安装目录。缺失或校验不符: '+', '.join(missing))
    if missing:
        print(f'环境安装完成；{len(missing)} 个模型文件待补齐。放入 models/ 后再次运行安装入口检查。',flush=True)
    run(root, root / 'runtimes/node/bin/node', '--version')
    node = root/'runtimes/node/bin/node'
    run(root,node,'--input-type=module','-e',"import {createRequire} from 'node:module'; import fs from 'node:fs'; const r=createRequire(process.cwd()+'/services/downloader/scihub_browser.mjs'); const {chromium}=r('@playwright/test'); if(!fs.existsSync(chromium.executablePath()))throw Error('Chromium missing'); console.log('Browser runtime OK');")
    print('Environment checks passed. No model API or user project was accessed.', flush=True)


def installation_fingerprint(root):
    import hashlib
    locks = ['scripts/install/assets.json','scripts/install/marker-macos-arm64.lock',
             'scripts/install/downloader-macos-arm64.lock','services/downloader/package-lock.json']
    plan={'python':PYTHON,'node':NODE['sha256'],'rust':RUST,'rustup':RUSTUP['sha256'],
          'locks':{name:digest(root/name) for name in locks}}
    return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=SOURCE)
    parser.add_argument('--assets', type=Path, help='Verified Marker/font asset ZIP supplied with the source release')
    parser.add_argument('--uv', default=shutil.which('uv'), help='Path to uv (>=0.6.6)')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--check', action='store_true', help='Read-only import and asset checks; no installation')
    parser.add_argument('--dev-tools', action='store_true', help='Also install frontend and Rust build tools (requires Xcode CLT)')
    args = parser.parse_args()
    root = args.root.absolute()
    if root.resolve() != root:
        raise ValueError('Root must be a physical checkout path, not a symlink')
    if args.check:
        verify(root)
        from release_manifest import check_app
        check_app(root)
        return
    fingerprint = installation_fingerprint(root)
    state = preflight(root, fingerprint)
    print('Target:', root)
    print('Install: Python 3.12.9, pinned downloader/Marker dependencies, Node 20.19.0, verified model/font assets.')
    print('Resources: supplied asset pack' if args.assets else 'Resources: supply models/ separately; download the verified font only')
    if not args.apply:
        print('Preview only. Use --apply on this clean checkout to install.')
        return
    if not args.uv:
        raise ValueError('Install uv first: https://docs.astral.sh/uv/getting-started/installation/')
    if args.dev_tools:
        subprocess.run(['xcode-select', '-p'], check=True, stdout=subprocess.DEVNULL)
    (root / 'runtimes').mkdir(exist_ok=True)
    (root / 'tmp').mkdir(exist_ok=True)
    import fcntl
    with (root / 'runtimes/install.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Re-read after acquiring the lock; another completed installer may have advanced it.
        state = preflight(root, fingerprint) if (root / 'runtimes/install-state.json').exists() else state
        state_path = root / 'runtimes/install-state.json'
        atomic_json(state_path, state)

        def stage(name, operation):
            if name not in state['done']:
                print('Installing:', name, flush=True)
                operation()
                state['done'].append(name)
                atomic_json(state_path, state)

        stage('python', lambda: install_python(root, args.uv))
        stage('node', lambda: install_node(root))
        # Models are supplied separately; only the small font is downloaded here.
        items=manifest(root)
        install(root, items if args.assets else [item for item in items if not item['path'].startswith('models/')], args.assets)
        npm = root / 'runtimes/node/lib/node_modules/npm/bin/npm-cli.js'
        node = root / 'runtimes/node/bin/node'
        stage('browser-npm', lambda: run(root,node,npm,'ci','--ignore-scripts','--no-audit','--no-fund','--prefix','services/downloader'))
        stage('chromium', lambda: run(root,node,root/'services/downloader/node_modules/playwright/cli.js','install','chromium'))
        if args.dev_tools:
            stage('npm', lambda: run(root, node, npm, 'ci', '--no-audit', '--no-fund'))

            def rust():
                installer = root / 'cache/install/rustup-init'
                locked_download(RUSTUP['url'], RUSTUP['sha256'], installer)
                installer.chmod(0o755)
                run(root, installer, '-y', '--no-modify-path', '--profile', 'minimal', '--default-toolchain', RUST)

            stage('rust', rust)
        verify(root,require_models=False)
        from release_manifest import check_app, register_installation
        check_app(root)
        register_installation(root)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'Setup stopped: {error}', file=sys.stderr)
        sys.exit(1)
