"""Hash-locked public resources. No user configuration or research data is read."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request
import zipfile


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(source):
    value = json.loads((Path(source) / 'scripts/install/assets.json').read_text())
    seen = set()
    for item in value['files']:
        name = item['path']
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or '\\' in name or name in seen:
            raise ValueError('Invalid or duplicate asset path')
        if not name.startswith(('models/marker/', 'services/marker/vendor/static/fonts/')):
            raise ValueError('Resource outside the asset allowlist')
        seen.add(name)
    return value['files']


def destination(root, name):
    root = Path(root).resolve()
    path = root / name
    # Do not follow a model/font symlink into another installation.
    if path.resolve() != path.absolute():
        raise ValueError(f'Refusing symlink asset path: {name}')
    return path


def matches(path, item):
    return path.is_file() and path.stat().st_size == item['bytes'] and digest(path) == item['sha256']


def receive(stream, path, item):
    """Publish only a complete, verified object; never overwrite a different file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.asset-', dir=path.parent)
    try:
        count = 0
        with os.fdopen(fd, 'wb') as out:
            while chunk := stream.read(1024 * 1024):
                count += len(chunk)
                if count > item['bytes']:
                    raise ValueError('Resource exceeds its locked size')
                out.write(chunk)
        if not matches(Path(temp), item):
            raise ValueError(f'Resource checksum mismatch: {item["path"]}')
        if path.exists():
            if not matches(path, item):
                raise ValueError(f'Existing resource differs: {item["path"]}')
        else:
            os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def install(root, items, pack=None):
    archive = zipfile.ZipFile(pack) if pack else None
    try:
        if archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate entries in asset pack')
            # No extractall: only exact locked paths are ever read or written.
            missing = {item['path'] for item in items} - set(names)
            if missing:
                raise ValueError('Incomplete asset pack: ' + ', '.join(sorted(missing)))
        for index, item in enumerate(items, 1):
            path = destination(root, item['path'])
            if path.exists():
                if matches(path, item):
                    continue
                raise ValueError(f'Existing resource differs; not overwritten: {item["path"]}')
            print(f'Asset {index}/{len(items)}: {item["path"]}', flush=True)
            if archive:
                with archive.open(item['path']) as stream:
                    receive(stream, path, item)
            else:
                request = urllib.request.Request(item['url'], headers={'User-Agent': 'ScholarNoteLM-Setup/1'})
                try:
                    with urllib.request.urlopen(request, timeout=120) as stream:
                        receive(stream, path, item)
                except Exception as exc:
                    raise RuntimeError(f'Cannot obtain {item["path"]}; use the matching --assets ZIP and retry. Existing verified files are retained.') from exc
    finally:
        if archive:
            archive.close()


def export(source, output):
    source, output = Path(source).resolve(), Path(output).absolute()
    items = manifest(source)
    if output.exists():
        raise ValueError('Output already exists; refusing overwrite')
    for item in items:
        if not matches(destination(source, item['path']), item):
            raise ValueError(f'Cannot export unverified resource: {item["path"]}')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.assets-', dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for item in items:
                archive.write(source / item['path'], item['path'])
            archive.write(source / 'scripts/install/assets.json', 'assets.json')
            archive.write(source / 'scripts/install/ASSET_NOTICES.md', 'ASSET_NOTICES.md')
            archive.write(source / 'scripts/install/FONT_NOTICE.txt', 'FONT_NOTICE.txt')
            archive.write(source / 'scripts/install/FONT_LICENSE.txt', 'FONT_LICENSE.txt')
        # Re-read the archive rather than assuming a completed write is valid.
        with zipfile.ZipFile(temp) as archive:
            for item in items:
                with archive.open(item['path']) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                        raise ValueError('Asset archive verification failed')
        os.replace(temp, output)
    finally:
        Path(temp).unlink(missing_ok=True)
    print(f'Created {output} (SHA-256 {digest(output)})')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    export(args.source, args.output)
