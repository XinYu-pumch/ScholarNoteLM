"""Paths for isolated integration fixtures; junctions need no Windows admin rights."""
import os
from pathlib import Path
import subprocess
import time


def python(root, runtime='downloader'):
    return Path(root)/'runtimes'/runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def cli(root):
    return Path(root)/'cache/tauri-target/debug'/('research-cli.exe' if os.name=='nt' else 'research-cli')


def wait_for_worker(pid, timeout=30):
    if not pid:return
    from engine import process_alive
    end=time.monotonic()+timeout
    while process_alive(pid) and time.monotonic()<end:
        time.sleep(.1)
    if process_alive(pid):raise AssertionError('Test worker did not exit after its terminal result')


def link_directory(link, target):
    link,target=Path(link).absolute(),Path(target).resolve()
    if link.exists() or link.is_symlink():
        raise ValueError('Test resource link already exists')
    if os.name=='nt':
        subprocess.run(['powershell.exe','-NoProfile','-Command',
                        'New-Item -ItemType Junction -Path $env:SCHOLAR_TEST_LINK -Target $env:SCHOLAR_TEST_TARGET -ErrorAction Stop | Out-Null'],
                       env={**os.environ,'SCHOLAR_TEST_LINK':str(link),'SCHOLAR_TEST_TARGET':str(target)},
                       check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        link.symlink_to(target,target_is_directory=True)
