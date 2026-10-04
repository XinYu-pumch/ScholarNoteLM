"""Bounded Altcha handshake through the current Chromium page, never curl.

No secrets leave this module through logs. The caller serializes the entire
handshake under its existing origin entry lock and accounts every subrequest.
"""
import asyncio
import base64
import hashlib
import html
import json
import re
import time
from urllib.parse import urljoin, urlsplit

MAX_NUMBER = 1_000_000
SOLVE_SECONDS = 2.0
ALGORITHMS = {'SHA-256': hashlib.sha256, 'SHA-384': hashlib.sha384, 'SHA-512': hashlib.sha512}

def challenge_url(markup, page_url):
    match = re.search(r'challengeurl\s*=\s*[\"\']([^\"\']+)[\"\']', markup, re.I)
    if not match:match = re.search(r'[\"\'](/captcha/challenge/[A-Za-z0-9_-]+)[\"\']', markup)
    if not match:return None
    url = urljoin(page_url, html.unescape(match.group(1)))
    source, target = urlsplit(page_url), urlsplit(url)
    if (source.scheme, source.netloc) != (target.scheme, target.netloc):return None
    if target.username or not re.fullmatch(r'/captcha/challenge/[A-Za-z0-9_-]+', target.path):return None
    return url

async def solve(challenge, timeout=SOLVE_SECONDS):
    """Cooperative CPU loop: bounded work, bounded wall time, cancellable."""
    if not isinstance(challenge, dict):return None
    algorithm = challenge.get('algorithm')
    if algorithm not in ALGORITHMS:return None
    maximum = challenge.get('maxNumber')
    salt, target, signature = (challenge.get(k) for k in ('salt', 'challenge', 'signature'))
    if type(maximum) is not int or not 0 <= maximum <= MAX_NUMBER:return None
    if not all(isinstance(x, str) and 0 < len(x) <= 4096 for x in (salt, target, signature)):return None
    digest = ALGORITHMS[algorithm]
    if not re.fullmatch('[0-9a-fA-F]{'+str(digest().digest_size*2)+'}', target):return None
    started = time.monotonic()
    for number in range(maximum + 1):
        if number % 1024 == 0:
            await asyncio.sleep(0)
            if time.monotonic() - started >= min(timeout, SOLVE_SECONDS):return None
        if digest(f'{salt}{number}'.encode()).hexdigest() == target.lower():
            return dict(algorithm=algorithm, challenge=target, number=number, salt=salt,
                        signature=signature, took=int((time.monotonic()-started)*1000))
    return None

async def unlock(markup, page_url, request, remaining, account, remember):
    url = challenge_url(markup, page_url)
    if not url:return False, 'unsupported_challenge'
    response = await request(url, 'GET', None)
    if response is None:return False, 'challenge_fetch_failed'
    try:challenge = json.loads(response.content)
    except (ValueError, TypeError):return False, 'invalid_challenge'
    started = time.monotonic()
    try:solution = await solve(challenge, max(0, remaining()))
    finally:account(time.monotonic()-started)
    if solution is None:return False, 'challenge_unsolved'
    payload = base64.b64encode(json.dumps(solution, separators=(',', ':')).encode()).decode()
    response = await request(url.replace('/challenge/', '/solution/', 1), 'POST', {'captcha': payload})
    if response is None:return False, 'challenge_submit_failed'
    try:accepted = json.loads(response.content).get('success') is True
    except (ValueError, TypeError, AttributeError):accepted = False
    if not accepted:return False, 'challenge_rejected'
    await remember()
    return True, 'challenge_solved'
