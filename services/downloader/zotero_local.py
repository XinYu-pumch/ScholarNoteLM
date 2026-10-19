"""Strict, read-only Local API client. No Connector, remote URLs or DB fallback.

Blocking file operations run only in zotero_worker, never in the download loop.
The supervisor imposes wall-clock deadlines even during PDF parsing/file I/O.
"""
from file_identity import change_ns
import managed_sqlite
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import random
import re
import stat
import unicodedata
from urllib.parse import urlsplit, unquote
from urllib.request import url2pathname

RULES = json.loads((Path(__file__).parent/'resources/zotero-pdf-title-list.v2.json').read_text())
PROBE_SECONDS = 2
REQUEST_SECONDS = 3
DOI_SECONDS = 15
STAGE_SECONDS = 60
MAX_BODY = 4 * 1024 * 1024
MAX_PAGES = 50
MAX_ITEMS = 5000
MAX_PDF = 256 * 1024 * 1024


def normalize_title(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split()).casefold()


ALIASES = {normalize_title(alias): rule for rule in RULES['entries'] for alias in rule['aliases']}


def normalize_doi(value):
    value = str(value or '').strip()
    value = re.sub(r'^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)', '', value, flags=re.I)
    return value.strip().lower()


def api_address(value):
    value = str(value or '').strip()
    if not value:
        return ''
    u = urlsplit(value if '://' in value else 'http://' + value)
    host = u.hostname
    if host == 'localhost':
        host = '127.0.0.1'  # Never resolve configurable hostnames or use environment proxies.
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError()
        port = u.port or 23119
    except (ValueError, TypeError):
        raise ValueError('Zotero 地址必须是本机回环地址') from None
    if u.scheme not in ('http', 'https') or u.username or u.password or u.query or u.fragment:
        raise ValueError('Zotero 地址必须是无认证参数的本机 HTTP(S) 地址')
    if any(part != 'api' for part in u.path.split('/') if part):
        raise ValueError('Zotero 地址只需填写主机、端口和可选 /api/')
    host = f'[{host}]' if ':' in host else host
    return f'{u.scheme}://{host}:{port}/api/'


def negative_name(value):
    value = normalize_title(value)
    # Deliberately don't reject data/table/figure/support/s1/appendix alone.
    if any(x in value for x in ('补充材料', '补充信息')):
        return True
    return bool(re.search(
        r'(?<![a-z0-9])(?:supplement(?:ary)?|supporting[\s_.-]+information|'
        r'table[\s_.-]+of[\s_.-]+contents|toc)(?![a-z0-9])', value))


def negative_path(value):
    # Inspect decoded path components, never hostname/query/fragment.
    for segment in unquote(urlsplit(value).path).split('/'):
        if negative_name(segment):
            return True
        # Confirmed publisher supplement conventions, with filename boundaries.
        if re.search(r'(?i)(?:^|[_\-.])(?:supp\d*|mmc\d+|esm\d*|moesm\d+)(?:[_\-.]|$)', segment):
            return True
    return False


def attachment_rule(data):
    if data.get('deleted') or data.get('itemType') != 'attachment' or data.get('linkMode') != 'imported_url':
        return None
    if str(data.get('contentType', '')).lower() != 'application/pdf':
        return None
    rule = ALIASES.get(normalize_title(data.get('title')))
    if not rule:
        return None
    try:
        url = data.get('url', '')
        if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
            return None
        u = urlsplit(url)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
            return None
        u.port  # reject malformed ports
        if negative_name(data.get('title')) or negative_name(data.get('filename')) or negative_path(data.get('filename', '')) or negative_path(data['url']):
            return None
    except (TypeError, ValueError):
        return None
    return rule


def file_path(value):
    u = urlsplit(value.strip())
    if u.scheme != 'file' or u.netloc.lower() not in ('', 'localhost') or u.query or u.fragment:
        raise ValueError('非本机文件 URL')
    # url2pathname performs exactly one percent decoding, including Windows drives.
    path = Path(url2pathname(u.path))
    if not path.is_absolute() or '\x00' in str(path):
        raise ValueError('无效文件 URL')
    return path


def fingerprint(path):
    if path.is_symlink():
        raise ValueError('不使用符号链接文件')
    try:
        s = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(s.st_mode):
        raise ValueError('不是普通文件')
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, change_ns(path,s)]


def rank(candidates, previous=None):
    # Stable within a batch once selected. Randomness only affects exact ties.
    random.SystemRandom().shuffle(candidates)
    return sorted(candidates, key=lambda c: (c['rule']['priority'], -c['stat'][2], c['key'] != previous))


class Unavailable(ValueError):
    pass


class LocalAPI:
    def __init__(self, address):
        import httpx
        self.client = httpx.AsyncClient(base_url=api_address(address), trust_env=False,
                                       follow_redirects=False, timeout=REQUEST_SECONDS,
                                       headers={'Zotero-API-Version': '3', 'Accept': 'application/json'})
        self.total_bytes = 0
        self.version = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def request(self, route, params=None):
        async with asyncio.timeout(REQUEST_SECONDS):
            async with self.client.stream('GET', route, params=params) as response:
                if response.status_code in (403, 404, 501):
                    raise Unavailable(f'Local API HTTP {response.status_code}')
                if response.status_code != 200:
                    raise Unavailable(f'Local API HTTP {response.status_code}（不跟随重定向）')
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    self.total_bytes += len(chunk)
                    if len(data) > MAX_BODY or self.total_bytes > 20 * MAX_BODY:
                        raise Unavailable('Local API 响应超过上限')
                return bytes(data), response.headers

    async def page(self, route, params):
        body, headers = await self.request(route, params)
        try:
            result = json.loads(body)
            total = int(headers['Total-Results'])
            if not isinstance(result, list) or not 0 <= total <= MAX_ITEMS or not all(
                    isinstance(v, dict) and isinstance(v.get('data'), dict) for v in result):
                raise ValueError()
            version = headers.get('Last-Modified-Version')
            if self.version is not None and version != self.version:
                raise ValueError()
            self.version = version
            return result, total
        except (ValueError, KeyError, TypeError):
            raise Unavailable('Local API 列表格式错误、超限或读取期间库已改变') from None

    async def probe(self):
        # Test the actual personal-library endpoint, never Connector /connector/ping.
        await self.page('users/0/items/top', {'limit': 1})

    async def pages(self, route, **params):
        result, seen, expected = [], set(), None
        for _ in range(MAX_PAGES):
            page, total = await self.page(route, {**params, 'start': len(result), 'limit': 100,
                                                  'sort': 'dateAdded', 'direction': 'asc', 'includeTrashed': 0})
            if expected is not None and total != expected:
                raise Unavailable('Local API 分页集合已改变')
            expected = total
            if len(result) + len(page) > total or len(page) > 100:
                raise Unavailable('Local API 分页不完整')
            for item in page:
                key = item.get('key') or item['data'].get('key')
                if not isinstance(key, str) or not re.fullmatch(r'[A-Z0-9]{8}', key) or key in seen:
                    raise Unavailable('Local API 条目键或分页重复')
                seen.add(key)
                result.append({**item['data'], 'key': key})
            if len(result) == total:
                return result
            if not page:
                raise Unavailable('Local API 分页提前结束')
        raise Unavailable('Local API 分页超过上限')

    async def candidates(self, doi):
        parents = await self.pages('users/0/items/top', q=doi, qmode='everything')
        parents = [p for p in parents if not p.get('deleted') and p.get('itemType') not in
                   ('attachment', 'note', 'annotation') and normalize_doi(p.get('DOI')) == doi]
        attachments = {}
        for parent in parents:
            for a in await self.pages(f"users/0/items/{parent['key']}/children"):
                if a.get('parentItem') != parent['key']:
                    continue
                rule = attachment_rule(a)
                if rule:
                    attachments.setdefault(a['key'], {'key': a['key'], 'parent': parent['key'], 'data': a, 'rule': rule})
        candidates = []
        # Resolve every eligible path before selecting. No partial metadata set.
        for c in attachments.values():
            try:
                body, _ = await self.request(f"users/0/items/{c['key']}/file/view/url")
            except Unavailable as ex:
                if 'HTTP 404' in str(ex):
                    continue  # attachment disappeared; other candidates remain usable
                raise
            try:
                path = file_path(body.decode('utf-8'))
                if negative_name(path.name) or negative_path(path.as_uri()):
                    continue
                signature = fingerprint(path)
                if signature and 0 < signature[2] <= MAX_PDF:
                    candidates.append({**c, 'path': path, 'stat': signature})
            except (OSError, ValueError, UnicodeError):
                continue
        return candidates


def copy_checked(candidate, target, validate):
    source = candidate['path']
    if fingerprint(source) != candidate['stat']:
        raise ValueError('源文件已改变')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(source, flags), 'rb') as incoming, target.open('xb') as outgoing:
        s = os.fstat(incoming.fileno())
        signature = [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, change_ns(source,s,incoming.fileno())]
        if signature != candidate['stat'] or not stat.S_ISREG(s.st_mode):
            raise ValueError('源文件已改变')
        size = 0
        while chunk := incoming.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_PDF:
                raise ValueError('文件超过本地补充上限')
            outgoing.write(chunk)
        outgoing.flush()
    if size != candidate['stat'][2] or fingerprint(source) != candidate['stat']:
        raise ValueError('复制期间源文件已改变')
    before = fingerprint(target)
    checked = validate(target)
    if before != fingerprint(target):
        raise ValueError('校验期间暂存文件已改变')
    return checked, before


def cache_fingerprint(e, path, sha):
    """Cache only a just-published, prevalidated file under the article-files lock."""
    import sqlite3
    import corpus_files
    s = path.stat()
    signature = f'{s.st_size}:{s.st_mtime_ns}:{change_ns(path,s)}'
    with managed_sqlite.connect(corpus_files.base(e)/'metadata/file-fingerprints.sqlite3', timeout=.2) as db:
        db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,signature TEXT,sha TEXT)')
        db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?)',
                   (str(path.relative_to(corpus_files.base(e))), signature, sha))
