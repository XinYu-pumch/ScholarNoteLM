"""Build only the final standalone .app; clean temporary staging, without a ZIP."""
import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid

from install_assets import manifest as assets_manifest, matches
from release_manifest import source_files, sha, validate

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ('python', 'downloader', 'marker', 'retrieval', 'node', 'playwright')


def copy_tree(source, target, *, venv=False):
    def ignore(directory, names):
        skipped = {n for n in names if n in ('__pycache__', '.DS_Store', '.git', '.links') or n.endswith(('.pyc', '.pyo'))}
        if venv and Path(directory) == source/'bin':
            skipped.update(n for n in names if n not in ('python', 'python3', 'python3.12'))
        return skipped
    shutil.copytree(source, target, symlinks=True, ignore=ignore)


def records(payload):
    result = {}
    for directory, dirs, files in os.walk(payload, followlinks=False):
        for name in sorted(dirs+files):
            path = Path(directory)/name
            relative = path.relative_to(payload).as_posix()
            if path.is_symlink():
                link = os.readlink(path)
                if Path(link).is_absolute() or not path.resolve().is_relative_to(payload) or not path.exists():
                    raise ValueError('Nonportable or missing package link: '+relative)
                result[relative] = {'link': link}
            elif path.is_file():
                result[relative] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return result


def build(source_app, output):
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise ValueError('Build on an Apple Silicon Mac.')
    pairing = json.loads((source_app/'Contents/Resources/source-manifest.json').read_text())
    validate(ROOT, pairing)
    assets = assets_manifest(ROOT)
    for item in assets:
        if not matches(ROOT/item['path'], item):
            raise ValueError('Offline asset missing or changed: '+item['path'])
    output.mkdir(parents=True, exist_ok=True)
    target = output/'ScholarNoteLM.app'
    validate_target(target)
    if source_app.resolve() == target.resolve():
        raise ValueError('Source companion app and standalone output must differ.')
    with tempfile.TemporaryDirectory(prefix='.build-', dir=output) as stage:
        app = Path(stage)/'ScholarNoteLM.app'
        assemble(source_app, app, pairing, assets)
        publish(app, target)
    print('Built standalone:', target, flush=True)
    return target


def validate_target(target):
    if not target.exists() and not target.is_symlink():return
    if target.is_symlink():raise ValueError('Refusing linked output app.')
    info = target/'Contents/Info.plist'
    manifest = target/'Contents/Resources/standalone-manifest.json'
    if not info.is_file() or not manifest.is_file():
        raise ValueError('Output is not a generated standalone app; refusing to replace it.')
    if plistlib.loads(info.read_bytes()).get('CFBundleIdentifier') != 'com.scholarnotelm.standalone':
        raise ValueError('Output bundle belongs to another application.')


def publish(app, target):
    # Keep the old app until the replacement has been assembled and verified.
    validate_target(target)
    backup = target.with_name('.previous-'+uuid.uuid4().hex+'.app')
    had_previous = target.exists()
    if had_previous:target.rename(backup)
    try:
        app.rename(target)
    except BaseException:
        if had_previous:backup.rename(target)
        raise
    if had_previous:shutil.rmtree(backup)


def assemble(source_app, app, pairing, assets):
    shutil.copytree(source_app, app, symlinks=True)
    contents = app/'Contents'
    payload = contents/'Resources/payload'
    payload.mkdir()
    public = source_files(ROOT)
    for name in public:
        target = payload/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, target)
    for component in COMPONENTS:
        copy_tree(ROOT/'runtimes'/component, payload/'runtimes'/component,
                  venv=component in ('downloader', 'marker', 'retrieval'))
    copy_tree(ROOT/'services/downloader/node_modules', payload/'services/downloader/node_modules')
    for item in assets:
        target = payload/item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/item['path'], target)
    shutil.copy2(contents/'Resources/source-manifest.json', payload/'source-manifest.json')
    # All venv interpreters must resolve inside this bundle; no generated pip entry points.
    for kind in ('downloader', 'marker', 'retrieval'):
        cfg = payload/'runtimes'/kind/'pyvenv.cfg'
        cfg.write_text(''.join(line for line in cfg.read_text().splitlines(keepends=True)
                               if not line.startswith(('home = ', 'command = ', 'executable = '))))
    executable = contents/'MacOS/scholarnotelm'
    executable.rename(contents/'MacOS/scholarnotelm-core')
    subprocess.run(['/usr/bin/clang', '-arch', 'arm64', '-mmacosx-version-min=14.0', '-O2',
                    str(ROOT/'scripts/standalone/macos-launcher.c'), '-o', str(executable)], check=True)
    info = contents/'Info.plist'
    value = plistlib.loads(info.read_bytes())
    value.update(CFBundleIdentifier='com.scholarnotelm.standalone', CFBundleName='ScholarNoteLM',
                 CFBundleDisplayName='ScholarNoteLM', CFBundleExecutable='scholarnotelm')
    info.write_bytes(plistlib.dumps(value))
    # Sign nested app/code before recording hashes; outer signing must not mutate payload.
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    metadata = {'schemaVersion': 1, 'platform': 'macos-arm64', 'version': pairing['version'],
                'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'sourceTreeDirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip()),
                'sourceFiles': {name: sha(ROOT/name) for name in public}, 'files': records(payload)}
    (contents/'Resources/standalone-manifest.json').write_text(json.dumps(metadata, separators=(',', ':')))
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-app', type=Path, default=ROOT/'ScholarNoteLM.app')
    parser.add_argument('--output', type=Path, default=ROOT/'dist/macos-standalone')
    args = parser.parse_args()
    build(args.source_app.resolve(), args.output.resolve())
