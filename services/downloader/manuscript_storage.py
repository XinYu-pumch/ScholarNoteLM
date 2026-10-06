"""Lossless on-disk manuscript images, shared across snapshots in one workspace.

Only the storage representation changes. Readers recover the exact original
data URLs before validating the existing logical manuscript ID or exporting.
"""
import gzip
import hashlib
import re
import zlib

import review_service as outline

FORMAT = 'manuscript-shared-images-v1'
IMAGE = re.compile(r'data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+')
MAX_IMAGE_BYTES = 128 * 1024 * 1024


def asset_path(folder, digest):
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('稿件图片标识校验失败')
    return outline.safe(folder, 'assets', digest + '.data-url.gz')


def read_image(folder, digest):
    path = asset_path(folder, digest)
    try:
        with gzip.open(path, 'rb') as stream:
            raw = stream.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('稿件图片内容校验失败')
        value = raw.decode('ascii')
        if not IMAGE.fullmatch(value):
            raise ValueError('稿件图片格式校验失败')
        return value
    except (OSError, EOFError, UnicodeError, zlib.error) as exc:
        raise ValueError('稿件图片缺失或校验失败') from exc


def encode(value):
    seen = {}
    assets = {}

    def visit(node):
        if isinstance(node, list):
            return [visit(v) for v in node]
        if not isinstance(node, dict):
            return node
        result = {}
        for key, item in node.items():
            if key == 'dataUrl' and isinstance(item, str) and IMAGE.fullmatch(item):
                if item not in seen:
                    raw = item.encode('ascii')
                    if len(raw) > MAX_IMAGE_BYTES:
                        raise ValueError('稿件图片过大，未修改原稿')
                    digest = hashlib.sha256(raw).hexdigest()
                    assets[digest] = raw
                    seen[item] = digest
                result[key] = {'imageAsset': seen[item]}
            else:
                result[key] = visit(item)
        return result

    compact = {'storageFormat': FORMAT, 'payload': visit(value)}
    return compact, assets


def pack(folder, value, atomic):
    compact, assets = encode(value)
    for digest, raw in assets.items():
        path = asset_path(folder, digest)
        if not path.exists():
            atomic(path, gzip.compress(raw, mtime=0))
        if read_image(folder, digest).encode('ascii') != raw:
            raise ValueError('稿件图片写入校验失败')
    return compact


def unpack(folder, stored):
    if not isinstance(stored, dict):
        raise ValueError('稿件格式校验失败')
    if 'storageFormat' not in stored:
        return stored  # Legacy self-contained JSON remains readable without writes.
    if set(stored) != {'storageFormat', 'payload'} or stored['storageFormat'] != FORMAT:
        raise ValueError('稿件存储格式校验失败')
    images = {}

    def visit(node):
        if isinstance(node, list):
            return [visit(v) for v in node]
        if not isinstance(node, dict):
            return node
        result = {}
        for key, item in node.items():
            if key == 'dataUrl' and isinstance(item, dict):
                if set(item) != {'imageAsset'}:
                    raise ValueError('稿件图片引用校验失败')
                digest = item['imageAsset']
                asset_path(folder, digest)  # Validate before using it as a cache key.
                if digest not in images:
                    images[digest] = read_image(folder, digest)
                result[key] = images[digest]
            else:
                result[key] = visit(item)
        return result

    return visit(stored['payload'])
