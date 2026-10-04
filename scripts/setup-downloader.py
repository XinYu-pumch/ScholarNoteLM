"""Provision a project-local Python runtime and PDF dependencies with uv (macOS/Windows)."""
import os, pathlib, shutil, subprocess, sys, platform
root=pathlib.Path(__file__).resolve().parents[1]
uv=shutil.which('uv')
if not uv:raise SystemExit('Install uv, then run this script again. No system Python packages will be modified.')
env={**os.environ,'UV_CACHE_DIR':str(root/'cache/uv'),'UV_PYTHON_INSTALL_DIR':str(root/'runtimes/python'),'UV_PYTHON_BIN_DIR':str(root/'runtimes/python/bin'),'TMPDIR':str(root/'tmp'),'TEMP':str(root/'tmp'),'TMP':str(root/'tmp')}
(root/'tmp').mkdir(exist_ok=True)
def run(*args):subprocess.run([uv,*args],cwd=root,env=env,check=True)
machine=platform.machine().lower()
arch='aarch64' if machine in ['arm64','aarch64'] else 'x86_64'
target=f'cpython-3.12.9-macos-{arch}-none' if sys.platform=='darwin' else '3.12'
run('python','install',target)
python=next((root/'runtimes/python').glob('cpython-3.12*/python.exe'),None) if os.name=='nt' else next((root/'runtimes/python').glob(f'cpython-3.12*{arch}*/bin/python3.12'),None)
if not python:raise SystemExit('Project-local Python not found')
run('venv','--python',str(python),'runtimes/downloader')
venv=root/('runtimes/downloader/Scripts/python.exe' if os.name=='nt' else 'runtimes/downloader/bin/python')
run('pip','install','--python',str(venv),'-r','services/downloader/requirements.txt')
print('PDF download runtime is ready:',venv)
