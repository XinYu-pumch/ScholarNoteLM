"""Check cleanup boundaries in an isolated directory; never uses real caches."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='maintenance-check-', dir=ROOT/'tmp') as folder:
    base = Path(folder)
    (base/'scripts').mkdir()
    shutil.copy2(ROOT/'scripts/clean-generated.py', base/'scripts/clean-generated.py')
    cache = base/'cache/tauri-target/debug/deps'
    cache.mkdir(parents=True)
    (cache/'generated').write_text('rebuildable')
    executable = base/'cache/tauri-target/debug/research-cli'
    executable.write_text('keep executable')
    paper = base/'workspace/project/pdf/123.pdf'
    paper.parent.mkdir(parents=True)
    paper.write_bytes(b'keep original')
    command = [sys.executable, str(base/'scripts/clean-generated.py')]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0 and cache.exists(), result.stderr
    result = subprocess.run(command+['--apply'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not cache.exists()
    assert executable.read_text() == 'keep executable' and paper.read_bytes() == b'keep original'
    retained = base/'retained'
    retained.mkdir()
    (retained/'important').write_text('keep')
    (base/'cache/vite').symlink_to(retained, target_is_directory=True)
    result = subprocess.run(command+['--apply'], capture_output=True, text=True)
    assert result.returncode != 0 and (retained/'important').read_text() == 'keep', 'symlink guard'
    (base/'cache/vite').unlink()
    (base/'cache/status-snapshots').mkdir()
    (base/'cache/status-snapshots/retained').write_text('busy')
    node = ROOT/('runtimes/node/node.exe' if os.name == 'nt' else 'runtimes/node/bin/node')
    child = subprocess.Popen([str(node), '-e', 'setInterval(()=>{},1000)', str(base)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        result = subprocess.run(command+['--apply'], capture_output=True, text=True)
        assert result.returncode != 0 and (base/'cache/status-snapshots/retained').exists(), 'active-process guard'
    finally:
        child.terminate()
        child.wait(timeout=5)
    print('PASS: preview, allowlist deletion, executable/project preservation, symlink rejection and active-process guard.')
