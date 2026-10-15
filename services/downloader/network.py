"""Current system proxy routing; never persist a proxy in project/model settings.

HTTPX only discovers environment proxies itself. urllib also reads the macOS
and Windows system settings. Resolve every request (including redirects), so a
long-lived download batch follows proxy changes without restarting the app.
"""
import ipaddress
import urllib.request
from urllib.parse import urlsplit

import httpx


def is_loopback(host):
    host = (host or '').lower().rstrip('.')
    if host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def system_proxy(url):
    parsed = urlsplit(str(url))
    if is_loopback(parsed.hostname) or urllib.request.proxy_bypass(parsed.netloc):
        return None
    proxies = urllib.request.getproxies()
    value = proxies.get(parsed.scheme) or proxies.get('all')
    if not value:
        return None
    if '://' not in value:
        value = 'http://' + value
    if urlsplit(value).scheme not in ('http', 'https'):
        raise ValueError('系统代理协议暂不支持，请使用系统 HTTP(S) 代理')
    return value


class SystemProxyTransport(httpx.AsyncBaseTransport):
    """Choose a connection pool per current route, without closing active streams.

    HTTPX calls the transport separately for each redirect, so local/bypassed
    destinations are re-evaluated even when a download changes hosts.
    """
    def __init__(self):
        self.transports = {}

    async def handle_async_request(self, request):
        proxy = system_proxy(request.url)
        if proxy not in self.transports:
            # Preserve the downloader's existing certificate environment support.
            # Proxy selection is explicit here; transports do not discover it.
            self.transports[proxy] = httpx.AsyncHTTPTransport(proxy=proxy, trust_env=True)
        request.extensions['network_mode'] = 'system_proxy' if proxy else 'direct'
        return await self.transports[proxy].handle_async_request(request)

    async def aclose(self):
        for transport in self.transports.values():
            await transport.aclose()
        self.transports.clear()
