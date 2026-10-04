"""Direct Europe PMC getPdf downloads; no FTP/ZIP or legacy deep-rescue adapter."""
import asyncio
import time

from pmc_parallel import GETPDF, normalize_pmcid
from scihub_retry import retry_after

ENDPOINT = 'https://europepmc.org/api/getPdf'
MAX_COOLDOWN_WAIT = 60


class Deferred(Exception):
    """A temporary failure should remain distinguishable from a missing PDF."""


class RateGate:
    """A 429 pauses all future getPdf requests in this batch, not S3 workers."""
    def __init__(self, retry_at=0.):
        self.until = time.monotonic() + max(0., retry_at - time.time())

    def defer(self, seconds):
        self.until = max(self.until, time.monotonic() + seconds)

    async def wait(self):
        while (remaining := self.until - time.monotonic()) > 0:
            if remaining > MAX_COOLDOWN_WAIT:
                raise Deferred('Europe PMC 限流等待超过本轮上限，留待手动重试')
            await asyncio.sleep(remaining)


async def download(engine, client, paper, path, batch, cfg, gate):
    httpx = engine.httpx
    pmcid = normalize_pmcid(paper.get('pmcid'))
    if not pmcid:
        return None, '没有有效 PMCID'
    url = f'{ENDPOINT}?pmcid={pmcid}'
    context = engine.HTTP_TRACE.get()
    if context:
        context[3].update(pmcid=pmcid, url=url, route='getPdf')
    attempts = cfg['europePmcAttempts']
    state = engine.progress(batch['id'], paper['pmid'])
    used = state.get('getPdfAttempts', 0)
    if used >= attempts:
        raise Deferred('getPdf 请求次数已用完（含中断请求），可手动重试')
    for n in range(used, attempts):
        await gate.wait()
        state['getPdfAttempts'] = n + 1
        engine.save_progress(batch['id'], paper['pmid'], state)
        try:
            async with asyncio.timeout(cfg['europePmcTimeout']):
                await engine.fetch_pdf(client, url, path, batch, paper['pmid'], GETPDF,
                    timeout=httpx.Timeout(cfg['europePmcTimeout'], connect=min(15, cfg['europePmcTimeout'])),
                    minimum_bytes=1024, strict_header=True, attempt_offset=n)
            return {'source': 'Europe PMC getPdf', 'pmcid': pmcid, 'url': url, 'route': 'getPdf'}, ''
        except asyncio.CancelledError:
            raise
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.HTTPStatusError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if status is not None and status not in (429, 500, 502, 503, 504):
                raise
            delay = 2 ** (n + 1)
            if status == 429:
                delay = max(delay, retry_after(exc.response.headers.get('retry-after')))
                gate.defer(delay)
                state['getPdfNextAttemptAt'] = time.time() + delay
                engine.save_progress(batch['id'], paper['pmid'], state)
            elif status is not None:
                delay = max(delay, retry_after(exc.response.headers.get('retry-after')))
            if n == attempts - 1:
                if status is None or status == 429:
                    raise Deferred('Europe PMC 请求超时、网络暂不可用或限流，留待手动重试') from exc
                raise
            if delay > MAX_COOLDOWN_WAIT:
                raise Deferred('Europe PMC 要求稍后重试，等待超过本轮上限') from exc
            engine.event(batch, paper['pmid'], GETPDF, '等待重试 getPdf', attempt=n+2, delaySeconds=delay, status=status)
            await asyncio.sleep(delay)
