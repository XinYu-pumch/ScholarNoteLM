"""Windows x64 source-install runtime. No system Python/npm/Rust is used."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import uuid

from install_assets import destination, digest, install, manifest, matches

SOURCE = Path(__file__).resolve().parents[1]
PLAN = json.loads((SOURCE/'scripts/install/windows-x64.json').read_text(encoding='utf-8'))


def environment(root):
    env = {**os.environ, 'UV_CACHE_DIR': str(root/'cache/uv'),
           'UV_PYTHON_INSTALL_DIR': str(root/'runtimes/python'),
           'UV_PYTHON_BIN_DIR': str(root/'runtimes/python/bin'),
           'UV_LINK_MODE': 'copy', 'UV_NO_CONFIG': '1',
           'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1',
           'PLAYWRIGHT_BROWSERS_PATH': str(root/'runtimes/playwright'),
           'CARGO_HOME': str(root/'cache/cargo'), 'RUSTUP_HOME': str(root/'runtimes/rust'),
           'CARGO_TARGET_DIR': str(root/'cache/tauri-target'),
           'npm_config_cache': str(root/'cache/npm'), 'SCHOLARNOTELM_ROOT': str(root),
           'TMP': str(root/'tmp'), 'TEMP': str(root/'tmp'), 'TMPDIR': str(root/'tmp'),
           'PATH': os.pathsep.join([str(root/'runtimes/node'), str(root/'cache/cargo/bin'), os.environ.get('PATH','')])}
    proxies = urllib.request.getproxies()
    for scheme in ('http', 'https'):
        if proxies.get(scheme) and not (env.get(scheme+'_proxy') or env.get(scheme.upper()+'_PROXY')):
            env[scheme.upper()+'_PROXY'] = proxies[scheme]
    env.setdefault('NO_PROXY', 'localhost,127.0.0.1,::1')
    env.setdefault('COMSPEC',str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/cmd.exe'))
    return env


def run(root, *args):
    subprocess.run([str(a) for a in args], cwd=root, env=environment(root), check=True)


def fingerprint(root):
    names = ['scripts/install/windows-x64.json', 'scripts/install/assets.json',
             'scripts/install/downloader-windows-x64.lock', 'scripts/install/marker-windows-x64.lock',
             'services/downloader/package-lock.json']
    return hashlib.sha256(json.dumps({n:digest(root/n) for n in names},sort_keys=True).encode()).hexdigest()


def preflight(root, signature):
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64','x86_64'):
        raise ValueError('This runtime requires Windows x64 (Intel/AMD).')
    if sys.getwindowsversion().major < 10:
        raise ValueError('Windows 10 or later is required.')
    if not (root/'services/downloader/engine.py').is_file():
        raise ValueError('Select the source installation folder, not a research folder.')
    for name in ('runtimes','models','cache','tmp','node_modules'):
        if (root/name).resolve() != root/name:
            raise ValueError(f'Refusing linked installation directory: {name}')
    state_path = root/'runtimes/install-state.json'
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('platform') != 'windows-x64' or state.get('fingerprint') != signature:
            raise ValueError('Installed manifest differs. Use a new checkout; no in-place runtime upgrades.')
        return state
    if any((root/n).exists() for n in ('runtimes','node_modules','cache/cargo')):
        raise ValueError('Existing unmanaged environment detected; use a clean checkout.')
    return {'schemaVersion':1, 'platform':'windows-x64', 'fingerprint':signature, 'done':[]}


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temp,path)


@contextmanager
def install_lock(root):
    import msvcrt
    with (root/'runtimes/install.lock').open('a+b') as guard:
        if guard.tell() == 0:
            guard.write(b'0'); guard.flush()
        guard.seek(0)
        try:
            msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:
            raise ValueError('Another installer is running.') from exc
        try:
            yield
        finally:
            guard.seek(0); msvcrt.locking(guard.fileno(),msvcrt.LK_UNLCK,1)


def download(root, name, item):
    path = root/'cache/install'/name
    if path.exists():
        if digest(path) != item['sha256']:
            raise ValueError(f'Cached download checksum mismatch: {path}')
        return path
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent,prefix='.download-')
    try:
        with os.fdopen(fd,'wb') as out, urllib.request.urlopen(item['url'],timeout=120) as response:
            shutil.copyfileobj(response,out)
        if digest(temporary) != item['sha256']:
            raise ValueError(f'Download checksum mismatch: {name}')
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def install_node(root):
    archive = download(root,'node-windows-x64.zip',PLAN['node'])
    target = root/'runtimes/node'
    with tempfile.TemporaryDirectory(dir=root/'tmp') as folder:
        with zipfile.ZipFile(archive) as bundle:
            # The archive is hash-locked; also reject paths outside extraction root.
            for name in bundle.namelist():
                if not (Path(folder)/name).resolve().is_relative_to(Path(folder).resolve()):
                    raise ValueError('Invalid Node archive path')
            bundle.extractall(folder)
        extracted = Path(folder)/PLAN['node']['directory']
        if target.exists():
            expected = {p.relative_to(extracted):digest(p) for p in extracted.rglob('*') if p.is_file()}
            actual = {p.relative_to(target):digest(p) for p in target.rglob('*') if p.is_file()}
            if actual != expected:
                raise ValueError('Existing Node differs; refusing overwrite.')
        else:
            # TemporaryDirectory has an owner-only Windows ACL. Publish a copy
            # inheriting the installation ACL, not that private extraction ACL.
            staging=target.with_name('.node-'+uuid.uuid4().hex)
            try:
                shutil.copytree(extracted,staging)
                os.replace(staging,target)
            finally:
                if staging.exists():shutil.rmtree(staging)


def repair_python_home(root):
    """Windows venv launchers need an absolute home; rebase owned environments after a move."""
    home = root/'runtimes/python'/PLAN['python']
    for name in ('downloader','marker','retrieval'):
        config = root/'runtimes'/name/'pyvenv.cfg'
        if not config.is_file():
            continue
        lines = [s for s in config.read_text(encoding='utf-8').splitlines() if not s.startswith('home = ')]
        config.write_text('\n'.join([f'home = {home}',*lines])+'\n',encoding='utf-8')


def install_python(root, uv):
    run(root,uv,'python','install',PLAN['python'])
    base = root/'runtimes/python'/PLAN['python']/'python.exe'
    for name in ('downloader','marker','retrieval'):
        target = root/'runtimes'/name
        if not (target/'pyvenv.cfg').is_file():
            run(root,uv,'venv','--python',base,target)
        repair_python_home(root)
        if name != 'retrieval':
            run(root,uv,'pip','sync','--python',target/'Scripts/python.exe','--require-hashes',
                '--only-binary',':all:',root/f'scripts/install/{name}-windows-x64.lock')
    site = root/'runtimes/retrieval/Lib/site-packages'
    site.mkdir(parents=True,exist_ok=True)
    (site/'scholarnotelm-shared.pth').write_text('../../../marker/Lib/site-packages\n',encoding='utf-8')


def verify(root, require_models=True):
    for name in ('downloader','marker','retrieval'):
        code = "import httpx,pypdf,bs4,lxml,docx,markdown,markdown_it; print('Base imports OK')"
        if name != 'downloader':
            code = ("import sys; from pathlib import Path; sys.path.insert(0,str(Path.cwd()/'services/marker/vendor')); "
                    "from marker.models import create_model_dict; from marker.config.parser import ConfigParser; "
                    "import numpy,torch,surya,transformers,marker.models; "
                    "assert transformers.__version__=='4.49.0'; "
                    "assert Path(marker.models.__file__).resolve().is_relative_to(Path.cwd()/'services/marker/vendor'); "
                    "print('Marker imports OK; torch',torch.__version__,'CUDA',torch.cuda.is_available())")
        prefix = ("import sys; from pathlib import Path; "
                  f"assert Path(sys.prefix).resolve()==(Path.cwd()/'runtimes/{name}').resolve(); "
                  "assert Path(sys.base_prefix).resolve().is_relative_to(Path.cwd()/'runtimes/python'); ")
        run(root,root/f'runtimes/{name}/Scripts/python.exe','-c',prefix+code)
    missing = [i['path'] for i in manifest(root) if not matches(destination(root,i['path']),i)]
    if missing:
        message = 'Models/font missing or different: '+', '.join(missing)
        if require_models:
            raise ValueError(message)
        print(message,flush=True)
    node = root/'runtimes/node/node.exe'
    run(root,node,'--input-type=module','-e',"import {createRequire} from 'node:module'; const r=createRequire(process.cwd()+'/services/downloader/scihub_browser.mjs'); const {chromium}=r('@playwright/test'); const b=await chromium.launch({headless:true}); console.log('Chromium OK',b.version()); await b.close();")
    from release_manifest import check_app
    check_app(root)
    print('Runtime checks passed. No user projects or model API were accessed.',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=SOURCE)
    parser.add_argument('--uv',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--dev-tools',action='store_true')
    args = parser.parse_args()
    root = args.root.absolute()
    if root.resolve() != root:
        raise ValueError('Select a physical installation directory.')
    if args.check:
        verify(root); return
    signature = fingerprint(root)
    state = preflight(root,signature)
    if not args.apply:
        print('Preview: Python 3.12.9, locked Windows wheels, Node, Chromium and font. Use --apply.'); return
    (root/'runtimes').mkdir(exist_ok=True); (root/'tmp').mkdir(exist_ok=True)
    with install_lock(root):
        if (root/'runtimes/install-state.json').exists():
            state = preflight(root,signature)
        def save():
            atomic_json(root/'runtimes/install-state.json',state)
        save()
        repair_python_home(root)
        def stage(name,operation):
            if name not in state['done']:
                print('Installing:',name,flush=True)
                operation(); state['done'].append(name); save()
        stage('python',lambda:install_python(root,args.uv))
        stage('node',lambda:install_node(root))
        install(root,[i for i in manifest(root) if not i['path'].startswith('models/')])
        node = root/'runtimes/node/node.exe'
        npm = root/'runtimes/node/node_modules/npm/bin/npm-cli.js'
        stage('browser-npm',lambda:run(root,node,npm,'ci','--ignore-scripts','--no-audit','--no-fund','--prefix','services/downloader'))
        stage('chromium',lambda:run(root,node,root/'services/downloader/node_modules/playwright/cli.js','install','chromium'))
        if args.dev_tools:
            stage('npm',lambda:run(root,node,npm,'ci','--no-audit','--no-fund'))
            def rust():
                installer = download(root,'rustup-init.exe',PLAN['rustup'])
                run(root,installer,'-y','--no-modify-path','--profile','minimal','--default-toolchain',PLAN['rust'],
                    '--default-host','x86_64-pc-windows-msvc')
            stage('rust',rust)
        verify(root,require_models=False)
        from release_manifest import register_installation
        register_installation(root)


if __name__ == '__main__':
    try:
        main()
    except (ValueError,RuntimeError,OSError,subprocess.CalledProcessError) as error:
        print(f'Setup stopped: {error}',file=sys.stderr)
        sys.exit(1)
