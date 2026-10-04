"""Bounded Sci-Hub requests, with independent entry/file health and durable cooldowns.

Production uses real Chromium navigation and a bounded, explicit Altcha handshake.
The caller persists item budgets and supplies PDF validation before a mirror is successful.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
import re
import time
from pathlib import Path
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
import scihub_identity
import scihub_altcha

FIRST_DELAY = (0, 0)  # The intervening OA stage separates the two passes.
MIRROR_COOLDOWN = (60, 120)
RETRY_BUDGET = 75
FILE_TIMEOUT = 30
ENTRY_TIMEOUT = 12
WAIT_BUDGET = 30


def retry_after(value, now=None):
    now = time.time() if now is None else now
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return 0


def safe_url(url):
    u = urlsplit(str(url))
    path = re.sub(r'(/captcha/(?:challenge|solution)/)[^/]+', r'\1[redacted]', u.path)
    return urlunsplit((u.scheme, u.hostname or '', path, '', ''))


def exception_kind(exc):
    if getattr(exc, 'kind', None):return exc.kind
    if isinstance(exc, TimeoutError):
        return 'timeout'
    text = str(exc).lower()
    if 'certificate' in text or 'curl: (60)' in text:
        return 'tls_certificate'
    if 'timeout' in text or 'timed out' in text or 'curl: (28)' in text:
        return 'timeout'
    return 'network_error'


def response_kind(status):
    if status == 429:
        return 'rate_limited'
    if status == 403:
        return 'forbidden'
    if status in (500, 502, 503, 504):
        return 'temporary_server_error'
    return 'http_error'


class EntryLock:
    """OS lock also serializes entry requests from separate project worker processes."""
    def __init__(self,path):
        self.path=path
        self.local=asyncio.Lock()
        self.file=None

    def locked(self):return self.local.locked()

    async def acquire(self):
        await self.local.acquire()
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.file=self.path.open('a+b')
            if self.file.tell()==0:self.file.write(b'0');self.file.flush()
            while True:
                try:
                    if os.name=='nt':
                        import msvcrt
                        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    return True
                except (BlockingIOError,PermissionError):await asyncio.sleep(.05)
        except BaseException:
            if self.file:self.file.close();self.file=None
            self.local.release()
            raise

    def release(self):
        if self.file:self.file.close();self.file=None
        self.local.release()


class MirrorHealth:
    def __init__(self, records=None, save=None, clock=time.time, jitter=random.uniform,lock_dir=None):
        self.records = records or {}
        self.save = save or (lambda key, value: None)
        self.clock, self.jitter = clock, jitter
        self.locks = {}
        self.lock_dir=Path(lock_dir) if lock_dir else None
        # Old policy inferred mirror outages from a single article response.
        for key, state in self.records.items():
            if state.get('policy') != 2 and state.get('lastError') not in ('rate_limited', 'tls_certificate'):
                state.update(nextAttemptAt=0, failedArticles=[], policy=2)
                self.save(key, dict(state))

    def key(self, role, url):
        # Entry health belongs to the configured mirror; storage health to the origin.
        u = urlsplit(url)
        endpoint = url.rstrip('/') if role == 'entry' else urlunsplit((u.scheme, u.netloc, '', '', ''))
        return role + ':' + endpoint

    def state(self, role, url):
        return self.records.setdefault(self.key(role, url), {})

    def lock(self, role, url):
        # Normalize aliases/case/default ports so one entry cannot acquire two locks.
        u = urlsplit(url)
        port = u.port or (443 if u.scheme.lower() == 'https' else 80)
        key = (role, u.scheme.lower(), (u.hostname or '').lower(), port)
        if key not in self.locks:
            self.locks[key]=EntryLock(self.lock_dir/(hashlib.sha256(repr(key).encode()).hexdigest()+'.lock')) if role=='entry' and self.lock_dir else (asyncio.Semaphore(2) if role == 'file' else asyncio.Lock())
        return self.locks[key]

    def available_at(self, role, url):
        state = self.state(role, url)
        return float('inf') if state.get('disabled') else state.get('nextAttemptAt', 0)

    def update(self, role, url, kind, retry_seconds=0, article=None):
        state = self.state(role, url)
        state['policy'] = 2
        now = self.clock()
        if kind == 'success':
            state.update(consecutiveFailures=0, failedArticles=[], lastSuccess=now, nextAttemptAt=0, disabled=False)
        else:
            n = state.get('consecutiveFailures', 0) + 1
            state.update(consecutiveFailures=n, lastFailure=now, lastError=kind)
            if kind == 'tls_certificate':
                state['disabled'] = True
            elif kind == 'rate_limited':
                delay = self.jitter(*MIRROR_COOLDOWN)
                state['nextAttemptAt'] = max(state.get('nextAttemptAt', 0), now + max(delay, retry_seconds))
            elif kind in ('timeout', 'network_error', 'temporary_server_error'):
                # A single DOI response is not evidence that the whole mirror is down.
                failed = list(dict.fromkeys([*state.get('failedArticles', []), *([article] if article else [])]))[-3:]
                state['failedArticles'] = failed
                if len(failed) >= 3:
                    state['nextAttemptAt'] = max(state.get('nextAttemptAt', 0), now + self.jitter(*MIRROR_COOLDOWN))
                    state['failedArticles'] = []
            else:
                state['failedArticles'] = []
            # Even uncommon HTTP responses must honor a supplied Retry-After.
            if retry_seconds:
                state['nextAttemptAt'] = max(state.get('nextAttemptAt', 0), now + retry_seconds)
        self.save(self.key(role, url), dict(state))


async def download(doi, path, mirrors, health, emit, validate, *, timeout=20,
                   supplemental=False, used=0, consume=lambda: None,
                   deadline=None, session_factory=None, budget=None, on_entry=lambda mirror: None,
                   known_files=(), known_pages=(), on_cached=lambda url: None, title='',
                   on_unverifiable=lambda path, evidence, source: None):
    """One bounded pass over the supplied mirrors, each mirror visited once, with bounded internal recovery requests.

    Cooldowns happen outside locks. A request budget is consumed only after acquiring
    the entry lock and rechecking health. asyncio cancellation propagates throughout.
    """
    import badr_sources as badr
    import scihub_browser
    import scihub_candidates
    session_factory = session_factory or scihub_browser.session
    remaining = list(dict.fromkeys([*known_pages, *mirrors]))
    doi = badr.normalize_doi_for_scihub(doi)
    seen_files = set()
    last_identity = {}
    last_validation = None
    last_fingerprint = None
    file_status = {}
    shard_rescues = 0
    file_requests_limit = 24
    timings = dict(queueSeconds=0., cooldownSeconds=0., lookupSeconds=0., downloadSeconds=0., validationSeconds=0.)
    requests = []
    # Mutable counters are persisted by the caller even on cancellation. Network and
    # waiting limits are independent: another article's cooldown cannot use HTTP time.
    budget = budget if budget is not None else {'network': 0., 'wait': 0., 'networkLimit': RETRY_BUDGET,
                                                'waitLimit': max(0., deadline-time.time()) if deadline else 0.}

    def deferred(message, **extra):
        emit(message, kind='deferred', **extra)

    async def acquire(lock):
        start = time.monotonic()
        try:
            async with asyncio.timeout(max(.001, budget['waitLimit']-budget['wait'])):
                await lock.acquire()
            return True
        except TimeoutError:
            deferred('排队等待达到上限，尚未获得本次请求机会')
            return False
        finally:
            elapsed = time.monotonic()-start
            timings['queueSeconds'] += elapsed
            budget['wait'] += elapsed

    async def wait_until(when):
        delay = max(0, when - time.time())
        if not delay:
            return True
        if budget.get('deferCooldown'):
            return False
        if delay > max(0., budget['waitLimit']-budget['wait']):
            return False
        emit('等待镜像恢复', kind='cooldown', nextAttemptAt=when)
        start = time.monotonic()
        try:
            await asyncio.sleep(delay)
        finally:
            elapsed = time.monotonic() - start
            timings['cooldownSeconds'] += elapsed
            budget['wait'] += elapsed
        return True

    async def get(browser, url, role, endpoint, mirror, protocol=None):
        start = time.monotonic()
        record = dict(role=role, mirror=safe_url(mirror), url=safe_url(url), transport=getattr(browser, 'transport', 'test-client'))
        if protocol:record['requestType']='challenge_'+protocol[0].lower()
        if budget['network'] >= budget['networkLimit']:
            deferred('实际请求时间达到上限');return None, record
        try:
            limit=max(.001,min(budget['networkLimit']-budget['network'],min(timeout, ENTRY_TIMEOUT) if role=='entry' else FILE_TIMEOUT))
            async with asyncio.timeout(limit):
                response = await browser.protocol(url, protocol[0], protocol[1], limit) if protocol else await browser.get(url, timeout=limit, allow_redirects=True, **({'role':role} if getattr(browser,'transport',None) else {}))
            record.update(getattr(response,'metrics',{}), method=getattr(response,'method','test-client'))
            record.update(status=response.status_code, finalUrl=safe_url(getattr(response, 'url', url)),
                          bytes=len(response.content),finalHost=urlsplit(str(getattr(response,'url',url))).hostname,
                          retryAfter=response.headers.get('retry-after', response.headers.get('Retry-After', '')))
            if response.status_code != 200 and not (role=='entry' and not protocol and response.status_code==403 and scihub_altcha.challenge_url(response.text, str(getattr(response,'url',url)))):
                record['kind'] = response_kind(response.status_code)
                health.update(role, endpoint, record['kind'], retry_after(record['retryAfter']), article=doi)
                if health.available_at(role, endpoint) > time.time():
                    deferred('来源进入冷却，保留服务器要求的等待时间', role=role, url=safe_url(endpoint))
                return None, record
            return response, record
        except asyncio.CancelledError:
            record['kind'] = 'interrupted'
            raise
        except Exception as exc:
            record.update(getattr(exc,'metrics',{}), kind=exception_kind(exc), error=re.sub(r'https?://[^\s]+', lambda m:safe_url(m.group()), str(exc))[:1000])
            health.update(role, endpoint, record['kind'], article=doi)
            return None, record
        finally:
            elapsed = time.monotonic() - start
            record['seconds'] = round(elapsed, 3)
            if role=='file' and 'bytes' in record:record['averageBytesPerSecond']=round(record['bytes']/max(.001,elapsed),1)
            timings['lookupSeconds' if role == 'entry' else 'downloadSeconds'] += elapsed
            budget['network'] += elapsed
            requests.append(record)
            if record.get('kind') == 'interrupted':
                emit('请求已中断', **record)

    async def check(response, url, role, endpoint, expected_sha=None):
        nonlocal last_identity, last_validation, last_fingerprint
        last_identity = {}
        last_validation = last_fingerprint = None
        if not response.content[:5].startswith(b'%PDF'):
            health.update(role, endpoint, 'non_pdf')
            return False
        path.write_bytes(response.content)
        start = time.monotonic()
        try:
            # Both structural validation and text extraction run in a killable child.
            last_identity = await scihub_identity.verify(path, doi, title)
            last_validation = last_identity.pop('validation', None)
            last_fingerprint = last_identity.pop('fingerprint', None)
            if last_identity.get('fileValid') is False:
                health.update(role, endpoint, 'invalid_pdf')
                return False
            last_identity['cacheHash'] = ('same' if expected_sha == last_identity.get('sha256') else 'changed') if expected_sha else 'none'
            if last_identity['status'] != 'match':
                if last_identity['status'] == 'unverifiable':
                    host = urlsplit(str(getattr(response,'url',url))).hostname or ''
                    on_unverifiable(path, last_identity, {'url':safe_url(getattr(response,'url',url)), 'source':'Sci-Net' if host=='sci-net.xyz' or host.endswith('.sci-net.xyz') else 'Sci-Hub'})
                emit('PDF 身份不匹配' if last_identity['status']=='mismatch' else 'PDF 身份待核验，未发布到文献库',
                     kind='identity_'+last_identity['status'], identity=last_identity, url=safe_url(url))
                return False
            return True
        finally:
            if last_identity.get('status') != 'match':path.unlink(missing_ok=True)
            timings['validationSeconds'] += time.monotonic() - start

    def result(response, url, mirror, route, page_url=None):
        final_url = str(getattr(response, 'url', url) or url)
        host = urlsplit(final_url).hostname or ''
        info = {'source': 'Sci-Net' if host == 'sci-net.xyz' or host.endswith('.sci-net.xyz') else 'Sci-Hub',
                'mirror': safe_url(mirror), 'url': safe_url(final_url), 'route': route, 'fileUrl': None,
                'transport':getattr(response,'metrics',{}).get('transport','test-client'),
                'browserVersion':getattr(response,'metrics',{}).get('browserVersion',''),
                'transferMethod':getattr(response,'method','test-client'), 'identity':dict(last_identity), 'shardRescues':shard_rescues,
                '_checked':last_validation, '_fingerprint':last_fingerprint}
        # Cache only durable unsigned public URLs. Logs never contain query tokens.
        if not urlsplit(final_url).query and not urlsplit(final_url).username:
            info['fileUrl'] = final_url.split('#')[0]
        if page_url and not urlsplit(page_url).query and not urlsplit(page_url).username:
            info['pageUrl'] = page_url.split('#')[0]
        return info

    async def fetch_file(browser, url, mirror, expected_sha=None, page_url=None, cached=False):
        if len(seen_files) >= file_requests_limit:
            deferred('候选文件请求数量达到本轮上限');return None
        if url in seen_files or urlsplit(url).scheme not in ('http', 'https'):
            return None
        seen_files.add(url)
        if budget['network'] >= budget['networkLimit']:
            deferred('实际请求时间达到上限，文件留待手动重试')
            return None
        when = health.available_at('file', url)
        if when > time.time() and not await wait_until(when):
            deferred('PDF 文件服务器暂不可用', role='file', url=safe_url(url))
            return None
        lock = health.lock('file', url)
        if not await acquire(lock):
            return None
        try:
            if health.available_at('file', url) > time.time():
                deferred('PDF 文件服务器暂不可用', role='file', url=safe_url(url))
                return None
            if cached:
                on_cached(url)
            response, record = await get(browser, url, 'file', url, mirror)
            file_status[url] = record.get('status')
            record['route'] = 'known-file' if cached else 'known-page-file' if mirror in known_pages else 'entry-file'
            if response is not None:
                valid = await check(response, url, 'file', url, expected_sha)
                record['kind'] = 'success' if valid else ('identity_'+last_identity['status'] if last_identity.get('status') and last_identity.get('fileValid') is not False else 'non_pdf' if not response.content[:5].startswith(b'%PDF') else 'invalid_pdf')
                if last_identity:record['identity']=dict(last_identity)
                if valid:
                    health.update('file', url, 'success')
                    emit('历史地址 PDF 校验成功' if cached else 'PDF 下载及校验成功', **record)
                    return result(response, url, mirror, record['route'], page_url)
            emit('PDF 文件请求失败，继续其他来源', **record)
        finally:
            lock.release()
        return None

    try:
        async with session_factory() as browser:
            for item in known_files:
                info = await fetch_file(browser, item['url'], '', expected_sha=item.get('sha256') or 'unknown', cached=True)
                if info:
                    return info, timings, requests
            while remaining:
                if budget['network'] >= budget['networkLimit']:
                    deferred('实际请求时间达到上限，剩余镜像留待手动重试')
                    break
                now = time.time()
                available = [m for m in remaining if health.available_at('entry', m) <= now]
                if not available:
                    when = min(health.available_at('entry', m) for m in remaining)
                    if not await wait_until(when):
                        emit('镜像暂不可用，本轮不再请求', kind='deferred', nextAttemptAt=when if when != float('inf') else None)
                        break
                    continue
                # Use a free entry before queueing behind a successful but busy mirror.
                free = [m for m in available if not health.lock('entry', m).locked()]
                mirror = max(free or available, key=lambda m: (m in known_pages, health.state('entry', m).get('lastSuccess', 0)))
                remaining.remove(mirror)
                url = mirror if mirror in known_pages else mirror.rstrip('/') + '/' + doi
                entered = False
                challenge_attempted = False
                for page_round in range(3):
                    lock = health.lock('entry', mirror)
                    if not await acquire(lock):break
                    links = []
                    response = None
                    try:
                        if health.available_at('entry', mirror) > time.time():
                            deferred('镜像暂不可用', role='entry', url=safe_url(mirror));break
                        if budget['network'] >= budget['networkLimit']:
                            deferred('实际请求时间达到上限');break
                        if not entered:
                            if mirror in known_pages:on_cached(mirror)
                            else:on_entry(mirror)
                            if supplemental:consume();used += 1
                            entered = True
                        response, record = await get(browser, url, 'entry', mirror, mirror)
                        record['pageRound'] = page_round
                        if response is None:
                            emit('镜像入口请求失败', **record);break
                        if scihub_candidates.challenge_page(response.text) and not response.content[:5].startswith(b'%PDF') and not scihub_candidates.candidates(response.text, str(getattr(response,'url',url))):
                            if not challenge_attempted and hasattr(browser, 'protocol'):
                                challenge_attempted = True
                                record['kind'] = 'suspected_challenge'
                                async def protocol_request(target, method, payload):
                                    answer, trace = await get(browser, target, 'entry', mirror, mirror, protocol=(method, payload))
                                    emit('验证协议请求完成', **trace)
                                    return answer
                                def account(seconds):
                                    budget['network'] += seconds;timings['lookupSeconds'] += seconds
                                ok, reason = await scihub_altcha.unlock(response.text, str(getattr(response,'url',url)),
                                    protocol_request, lambda:budget['networkLimit']-budget['network'], account, browser.remember_cookies)
                                emit('验证通过' if ok else '验证未通过', kind=reason, mirror=safe_url(mirror))
                                if ok:
                                    response, record = await get(browser, url, 'entry', mirror, mirror)
                                    record.update(pageRound=page_round, requestType='challenge_replay')
                                    if response is None:break
                            if scihub_candidates.challenge_page(response.text) and not response.content[:5].startswith(b'%PDF') and not scihub_candidates.candidates(response.text, str(getattr(response,'url',url))):
                                record['kind']='suspected_challenge';health.update('entry',mirror,'suspected_challenge')
                                emit('疑似验证页，继续其他来源', **record);break
                        if response.content[:5].startswith(b'%PDF'):
                            valid = await check(response, url, 'entry', mirror, 'unknown' if mirror in known_pages else None)
                            record['identity']=dict(last_identity)
                            record['kind']='success' if valid else ('identity_'+last_identity['status'] if last_identity else 'invalid_pdf')
                            if valid:
                                health.update('entry', mirror, 'success');emit('入口直接返回有效 PDF', **record)
                                return result(response, url, mirror, 'known-page' if mirror in known_pages else 'entry'), timings, requests
                            emit('PDF 校验未通过', **record);break
                        page_url = str(getattr(response, 'url', url) or url)
                        links = scihub_candidates.candidates(response.text, page_url)
                        record['kind']='pdf_link_found' if links else 'no_pdf_link'
                        record['candidateCount']=len(links)
                        emit('已解析 PDF 候选链接' if links else '页面未解析到 PDF 链接', **record)
                        if links:health.update('entry',mirror,'success')
                    finally:
                        lock.release()
                    if not links:break
                    refresh = False
                    for candidate in links:
                        info = await fetch_file(browser, candidate, mirror, expected_sha='unknown' if mirror in known_pages else None, page_url=page_url)
                        if info:return info, timings, requests
                        if file_status.get(candidate) not in (404,410):continue
                        refresh = True
                        for alternative in scihub_candidates.shard_variants(candidate):
                            info = await fetch_file(browser, alternative, mirror, page_url=page_url)
                            if info:
                                shard_rescues += 1;info['shardRescues']=shard_rescues
                                emit('存储分片补救成功', kind='shard_rescue', shardRescues=shard_rescues, url=safe_url(alternative))
                                return info, timings, requests
                    if not refresh:break
                    # All subrequests count against this already-consumed mirror
                    # visit. Cancellation/resume cannot replay a fresh allowance.
                    if page_round < 2:emit('候选文件不存在，有限刷新文章页', kind='page_refresh', mirror=safe_url(mirror))
        return None, timings, requests
    finally:
        # Emitted on interruption too; no response bodies, cookies or credentials logged.
        emit('请求耗时明细', kind='timings', **{k: round(v, 3) for k, v in timings.items()})
        emit('实际请求计数', kind='request_count', entryRequests=sum(r['role']=='entry' for r in requests),
             fileRequests=sum(r['role']=='file' for r in requests))
