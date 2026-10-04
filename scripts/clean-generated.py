"""Preview (default) or remove reproducible build caches in this checkout.

Run after closing the app and development servers. Never removes executables,
installed dependencies, models, credentials, project data or historical backups.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    'cache/tauri-target/debug/deps',
    'cache/tauri-target/debug/build',
    'cache/tauri-target/debug/incremental',
    'cache/tauri-target/debug/.fingerprint',
    'cache/tauri-target/debug/examples',
    'cache/tauri-target/debug/bundle',
    'cache/vite',
    'cache/npm/_logs',
    'cache/status-snapshots',
)


def files(path):
    for directory, dirs, names in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in names:
            file = Path(directory) / name
            if not file.is_symlink():
                yield file


def active_processes():
    if os.name == 'nt':
        # A broad check is intentional: do not guess which Windows node/python
        # process owns an in-use cache when its command line is unavailable.
        output = subprocess.check_output(['tasklist', '/FO', 'CSV', '/NH'], text=True)
        return any(f'"{name}.exe"' in output.lower() for name in ('scholarnotelm', 'research-cli', 'cargo', 'node'))
    # macOS truncates `comm` to 16 characters when another column follows it.
    # Read it separately as the final column; paths may themselves contain spaces.
    output = subprocess.check_output(['ps', '-axo', 'pid=,comm='], text=True)
    commands = subprocess.check_output(['ps', '-ww', '-axo', 'pid=,args='], text=True)
    args_by_pid = dict(line.strip().split(None, 1) for line in commands.splitlines() if len(line.strip().split(None, 1)) == 2)
    for line in output.splitlines():
        columns = line.strip().split(None, 1)
        if len(columns) != 2 or int(columns[0]) in (os.getpid(), os.getppid()):
            continue
        pid, executable = columns
        args = args_by_pid.get(pid, '')
        name = Path(executable).name.lower()
        if name in ('scholarnotelm', 'research-cli', 'cargo', 'rustc'):
            return True
        if str(ROOT) in args and name.startswith(('node', 'python')):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Delete the listed caches; omit to preview.')
    args = parser.parse_args()
    if args.apply and active_processes():
        parser.error('请先退出 ScholarNoteLM、开发服务和后台任务，再执行清理。')
    total = 0
    candidates = []
    for relative in TARGETS:
        path = ROOT / relative
        # Reject symlink ancestors as well as a symlink at the deletion target.
        if path.resolve() != path.absolute():
            parser.error(f'拒绝清理符号链接路径：{relative}')
        if not path.exists():
            continue
        size = sum(file.stat().st_size for file in files(path))
        total += size
        candidates.append(path)
        print(f'{size / 2**20:9.1f} MiB  {relative}')
    print(f'合计 {total / 2**30:.2f} GiB（文件逻辑大小；实际释放空间受文件系统影响）')
    if args.apply:
        for path in candidates:
            shutil.rmtree(path)
        print('缓存已清理。下次开发启动需要重新编译；文献与运行程序均保留。')
    else:
        print('仅预览。确认退出应用后，加 --apply 执行。')


if __name__ == '__main__':
    main()
