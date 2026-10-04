"""Bounded rendered-DOM candidate extraction, shared by every Sci-Hub route."""
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup

MAX_CANDIDATES = 12

def candidates(html, page_url):
    # Saved SingleFile pages may contain megabytes of irrelevant PDF base64.
    html = re.sub(r'(data:)[^\s\"\'<>]{512,}', r'\1STRIPPED', html, flags=re.I)
    soup = BeautifulSoup(html, 'lxml')
    result = []
    def add(value):
        value = (value or '').strip()
        if not value or value.lower().startswith(('data:', 'about:', 'javascript:', 'blob:', '#')):
            return
        try:
            url = urljoin(page_url, value).split('#')[0]
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                return
        except ValueError:
            return
        if url not in result and len(result) < MAX_CANDIDATES:
            result.append(url)
    for node in soup.find_all('meta'):
        if (node.get('name') or '').lower() == 'citation_pdf_url':add(node.get('content'))
    for selector, attr in [('div.download a[href], a.download[href], div.pdf a[href]', 'href'),
                           ('object[data]', 'data'), ('iframe[src], embed[src]', 'src')]:
        for node in soup.select(selector):add(node.get(attr))
    for node in soup.select('a[href]'):
        href = node.get('href', '')
        if '/storage/' in href or re.search(r'\.pdf(?:[?#]|$)', href, re.I):add(href)
    return result

def shard_variants(url):
    """Hypotheses for this file only; a 404 never disables a whole shard."""
    match = re.match(r'^(https?://[^/]+/storage/)([^/]+)(/.*)$', url)
    if not match:return []
    base, shard, rest = match.groups()
    return [base + alternative + rest for alternative in ('2024', 'zero') if alternative != shard]

def challenge_page(html):
    lower = html.lower()
    return any(marker in lower for marker in ('captcha', 'checking your browser', 'altcha-widget', '/captcha/challenge'))
