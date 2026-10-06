"""Lossless storage for generated audit records; legacy plain files remain readable."""
import gzip
import json
from pathlib import Path


def compressed_path(path):
    return Path(str(path) + '.gz')


def read_text(path):
    path = Path(path)
    if path.suffix != '.gz' and path.is_file():
        return path.read_text(encoding='utf8')
    target = path if path.suffix == '.gz' else compressed_path(path)
    if target.is_symlink():
        raise ValueError('压缩记录不能使用符号链接')
    return gzip.decompress(target.read_bytes()).decode('utf8')


def read_json(path, default=None):
    if not path.is_file() and not compressed_path(path).is_file():
        return default
    return json.loads(read_text(path))


def write_text(e, path, text):
    """Publish gzip atomically before retiring the old uncompressed representation."""
    target = compressed_path(path)
    e.atomic(target, gzip.compress(text.encode('utf8'), compresslevel=6, mtime=0))
    path.unlink(missing_ok=True)
    return target


def write_json(e, path, value):
    return write_text(e, path, json.dumps(value, ensure_ascii=False, indent=2))
