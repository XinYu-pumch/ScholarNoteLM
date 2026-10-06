"""Explicit, lossless maintenance. Optional self-contained HTML resource pooling.

The CLI holds exclusive storage, review and corpus locks for application. A dry
run only reads files. Each file is independently verified and atomically replaced;
interruption leaves a readable mixture of legacy and compact storage.
"""
import gzip
import json
import re

import manuscript_storage as images
import review_manuscripts as manuscripts
import review_service as review
import storage
import html_compaction


def compact_project(e, apply=False, include_html=False):
    base = storage.project_dir(e.ROOT, e.PROJECT)
    plans = []
    asset_bytes = {}
    html_results = []
    before = after = 0
    review_root = review.safe(base, 'review')
    for work in sorted(review_root.iterdir()) if review_root.exists() else []:
        if work.is_symlink():
            raise ValueError('综述目录不能使用符号链接')
        if not work.is_dir():
            continue
        folder = review.safe(work, 'manuscripts')
        for directory in sorted(folder.iterdir()) if folder.exists() else []:
            if directory.name == 'assets':
                continue
            if directory.is_symlink():
                raise ValueError('稿件目录不能使用符号链接')
            if not directory.is_dir() or not re.fullmatch('[a-f0-9]{64}', directory.name):
                continue
            path = review.safe(directory, 'document.json')
            original = path.read_bytes()
            stored = json.loads(original)
            value = manuscripts.get(e, work.name, directory.name)
            if 'storageFormat' in stored:
                continue
            compact, assets = images.encode(value)
            for digest, raw in assets.items():
                target = images.asset_path(folder, digest)
                if target.exists():
                    if images.read_image(folder, digest).encode('ascii') != raw:
                        raise ValueError('稿件图片校验失败')
                else:
                    asset_bytes[target] = len(gzip.compress(raw, mtime=0))
            before += len(original)
            after += len(json.dumps(compact, ensure_ascii=False, indent=2).encode('utf8'))
            plans.append(('manuscript', path, original, work.name))
        if include_html:
            exports = review.safe(work, 'exports')
            for candidate in sorted(exports.rglob('*.html')):
                path = review.safe(base, *candidate.relative_to(base).parts)
                original = path.read_bytes()
                try:
                    result = html_compaction.compact_html(original.decode('utf8')).encode('utf8')
                except html_compaction.UnsupportedHTML as exc:
                    html_results.append({'path':str(path.relative_to(base)), 'skipped':str(exc)})
                    continue
                if result == original or len(result) >= len(original):
                    continue
                before += len(original)
                after += len(result)
                html_results.append({'path':str(path.relative_to(base)), 'beforeBytes':len(original), 'afterBytes':len(result)})
                plans.append(('html', path, original, result))

    chunks = review.safe(base, 'vectors', 'chunks')
    for path in sorted(chunks.glob('*.jsonl')):
        if path.is_symlink():
            raise ValueError('文本块文件不能使用符号链接')
        if not re.fullmatch(r'[0-9]+\.jsonl', path.name):
            continue
        original = path.read_bytes()
        target = review.safe(chunks, path.name + '.gz')
        compressed = gzip.compress(original, mtime=0)
        if target.exists():
            if gzip.decompress(target.read_bytes()) != original:
                raise ValueError('已有文本块压缩副本不同，原文件未修改')
            after += target.stat().st_size
            before += target.stat().st_size
        else:
            after += len(compressed)
        before += len(original)
        plans.append(('jsonl', path, original, compressed))

    # Preflight is complete before any legacy file is replaced.
    if apply:
        for kind, path, original, extra in plans:
            if path.read_bytes() != original:
                raise ValueError('文件在压缩期间发生变化，请稍后重试')
            if kind == 'manuscript':
                value = manuscripts.get(e, extra, path.parent.name)
                manuscripts.store(e, extra, value)
                if manuscripts.get(e, extra, path.parent.name) != value:
                    raise ValueError('压缩后稿件校验失败')
            elif kind == 'html':
                # compact_html already proved that scoped evidence and body image
                # URLs reconstruct exactly; publish without regenerating any prose.
                e.atomic(path, extra)
            else:
                target = path.with_name(path.name + '.gz')
                if not target.exists():
                    e.atomic(target, extra)
                if gzip.decompress(target.read_bytes()) != original:
                    raise ValueError('文本块压缩校验失败，原文件保留')
                if path.read_bytes() != original:
                    raise ValueError('文本块已变化，原文件保留')
                path.unlink()
    after += sum(asset_bytes.values())
    return {'project': e.PROJECT, 'applied': apply,
            'manuscripts': sum(p[0] == 'manuscript' for p in plans),
            'jsonlFiles': sum(p[0] == 'jsonl' for p in plans),
            'htmlFiles': sum(p[0] == 'html' for p in plans), 'htmlResults':html_results,
            'beforeBytes': before, 'afterBytes': after, 'savedBytes': before - after}
