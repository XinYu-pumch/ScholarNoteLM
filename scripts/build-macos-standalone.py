"""Package a complete Apple Silicon app; no user state or developer tools included."""
import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
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
    stage = output/('stage-'+uuid.uuid4().hex[:8])
    stage.mkdir()
    app = stage/'ScholarNoteLM.app'
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
    archive = output/f'ScholarNoteLM-{pairing["version"]}-macos-arm64-standalone.zip'
    archive.unlink(missing_ok=True)
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(archive)], check=True)
    archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
    (output/'latest-build.json').write_text(json.dumps({'app':str(app),'archive':str(archive)},indent=2))
    print('Built standalone:', app, flush=True)
    print('Archive:', archive, 'bytes:', archive.stat().st_size, flush=True)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-app', type=Path, default=ROOT/'ScholarNoteLM.app')
    parser.add_argument('--output', type=Path, default=ROOT/'dist/macos-standalone')
    args = parser.parse_args()
    build(args.source_app.resolve(), args.output.resolve())
