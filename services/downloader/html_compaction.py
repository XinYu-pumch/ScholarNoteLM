"""Content-addressed evidence and images inside one portable HTML file.

No fetches, companion files, image recompression, or changes to citation scopes.
Existing exports are transformed only when their embedded reader is recognized.
"""
import hashlib
import json
from pathlib import Path
import re

FORMAT = 'offline-evidence-pool-v1'
MARKER = '<script id="reference-data" type="application/json">'
IMAGE = re.compile(r'data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+')
BODY_IMAGE = re.compile(r'(<img\b[^>]*?\s)src=([\"\'])(data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+)\2')
BODY_REF = re.compile(r'(<img\b[^>]*?\s)data-image-ref=([\"\'])([a-f0-9]{64})\2')
# The previously shipped full offline reader. Older prototype/custom readers are
# deliberately left alone because their DOM and behavior can differ.
LEGACY_READER = '1ec5cb276a89c468f5eba10931d987bf767a084c873539596ec458757ce09825'


class UnsupportedHTML(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode('utf8')).hexdigest()


def parts(source):
    if source.count(MARKER) != 1:
        raise UnsupportedHTML('不是支持的综述 HTML，未修改')
    prefix, tail = source.split(MARKER, 1)
    data, close, tail = tail.partition('</script><script>')
    reader, end, suffix = tail.partition('</script>')
    if not close or not end:
        raise UnsupportedHTML('综述 HTML 脚本布局未知，未修改')
    return prefix, json.loads(data), reader, suffix


class Pool:
    def __init__(self):
        self.images = {}
        self.resources = {}
        self.entries = {}

    def intern(self, table, value):
        key = digest(value)
        table.setdefault(key, value)
        return key

    def image(self, url):
        if not isinstance(url, str) or not IMAGE.fullmatch(url):
            raise ValueError('HTML 图片格式无效')
        return self.intern(self.images, url)

    def resource(self, resource):
        value = dict(resource)
        url = value.get('dataUrl')
        if isinstance(url, str) and IMAGE.fullmatch(url):
            value['dataUrl'] = {'imageRef': self.image(url)}
        return self.intern(self.resources, value)

    def entry(self, entry):
        value = dict(entry) if isinstance(entry, dict) else entry
        if isinstance(value, dict) and 'resources' in value:
            value['resources'] = [self.resource(r) for r in value['resources']]
        return self.intern(self.entries, value)

    def pack(self, references):
        scopes = {scope: {pmid: [self.entry(e) for e in entries]
                          for pmid, entries in papers.items()}
                  for scope, papers in references.items()}
        return {'format': FORMAT, 'scopes': scopes, 'entries': self.entries,
                'resources': self.resources, 'images': self.images}


def unpack(stored):
    """Restore exact reference values for validation/tests; the browser is lazy."""
    if stored.get('format') != FORMAT:
        return stored
    if set(stored) != {'format', 'scopes', 'entries', 'resources', 'images'}:
        raise ValueError('HTML 资源池结构无效')
    for kind in ('entries', 'resources', 'images'):
        for key, value in stored[kind].items():
            if digest(value) != key:
                raise ValueError('HTML 资源池内容校验失败')
    for image in stored['images'].values():
        if not isinstance(image, str) or not IMAGE.fullmatch(image):
            raise ValueError('HTML 图片格式无效')
    resources = {}
    for key, resource in stored['resources'].items():
        value = dict(resource)
        if isinstance(value.get('dataUrl'), dict):
            reference = value['dataUrl']
            if set(reference) != {'imageRef'}:
                raise ValueError('HTML 图片引用无效')
            value['dataUrl'] = stored['images'][reference['imageRef']]
        resources[key] = value
    entries = {}
    for key, entry in stored['entries'].items():
        value = dict(entry) if isinstance(entry, dict) else entry
        if isinstance(value, dict) and 'resources' in value:
            value['resources'] = [resources[r] for r in value['resources']]
        entries[key] = value
    return {scope: {pmid: [entries[e] for e in refs] for pmid, refs in papers.items()}
            for scope, papers in stored['scopes'].items()}


def expand_body(prefix, stored):
    def image(match):
        return match[1] + 'src=' + match[2] + stored['images'][match[3]] + match[2]
    return BODY_REF.sub(image, prefix)


def compact_html(source):
    prefix, references, reader, suffix = parts(source)
    current_reader = Path(__file__).with_name('review_export.js').read_text(encoding='utf8')
    if references.get('format') == FORMAT:
        unpack(references)
        expand_body(prefix, references)
        return source
    if reader != current_reader and hashlib.sha256(reader.encode()).hexdigest() != LEGACY_READER:
        raise UnsupportedHTML('旧原型或自定义 HTML 阅读器不支持自动迁移，未修改')
    pool = Pool()
    compact = pool.pack(references)

    def image(match):
        return match[1] + 'data-image-ref=' + match[2] + pool.image(match[3]) + match[2]

    body = BODY_IMAGE.sub(image, prefix)
    if unpack(compact) != references or expand_body(body, compact) != prefix:
        raise ValueError('HTML 无损还原校验失败，原文件未修改')
    data = encoded(compact).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return body + MARKER + data + '</script><script>' + current_reader + '</script>' + suffix
