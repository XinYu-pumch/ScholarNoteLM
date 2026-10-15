"""Proxy switching with real local HTTP servers; no OS settings or external traffic."""
import asyncio
import json
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import network
import review_llm
import embedding_limits


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def respond(self):
        self.server.hits.append(self.path)
        if self.path.endswith('/redirect'):
            self.send_response(302)
            self.send_header('Location', self.server.redirect)
            self.end_headers()
            return
        payload = {'choices': [{'message': {'content': self.server.label}, 'finish_reason': 'stop'}]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self): self.respond()

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.respond()


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servers = []
        for label in ('direct', 'proxy-a', 'proxy-b'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.label = label
            server.hits = []
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.servers.append(server)
        self.direct, self.proxy_a, self.proxy_b = self.servers
        self.local = f'http://127.0.0.1:{self.direct.server_port}'
        self.remote = f'http://paper.test:{self.direct.server_port}'
        self.proxies = {}
        getproxies = patch('urllib.request.getproxies', side_effect=lambda: dict(self.proxies))
        bypass = patch('urllib.request.proxy_bypass', return_value=False)
        getaddrinfo = socket.getaddrinfo
        def resolve(host, *args, **kwargs):
            if host in ('paper.test', b'paper.test'): host = '127.0.0.1'
            # Reject unintended external traffic even if a test regresses.
            if host not in ('127.0.0.1', b'127.0.0.1', '::1', b'::1'):
                raise AssertionError('Unexpected network host')
            return getaddrinfo(host, *args, **kwargs)
        for p in (getproxies, bypass, patch('socket.getaddrinfo', side_effect=resolve)):
            p.start()
            self.addCleanup(p.stop)

    async def asyncTearDown(self):
        for server in self.servers:
            await asyncio.to_thread(server.shutdown)
            server.server_close()

    def route(self, server):
        self.proxies.clear()
        if server:
            self.proxies['http'] = f'http://127.0.0.1:{server.server_port}'

    async def test_download_batch_follows_on_off_and_changed_proxy(self):
        async with httpx.AsyncClient(transport=network.SystemProxyTransport(), trust_env=False) as client:
            for server, expected in ((None, 'direct'), (self.proxy_a, 'proxy-a'),
                                     (None, 'direct'), (self.proxy_b, 'proxy-b')):
                self.route(server)
                response = await client.get(self.remote + '/paper')
                self.assertEqual(response.json()['choices'][0]['message']['content'], expected)
        self.assertEqual(len(self.direct.hits), 2)
        self.assertEqual(len(self.proxy_a.hits), 1)
        self.assertEqual(len(self.proxy_b.hits), 1)

    async def test_redirects_recheck_destination_and_local_bypass(self):
        self.route(self.proxy_a)
        self.direct.redirect = self.remote + '/paper'
        self.proxy_a.redirect = self.local + '/paper'
        async with httpx.AsyncClient(transport=network.SystemProxyTransport(), trust_env=False, follow_redirects=True) as client:
            for url, expected in ((self.local, 'proxy-a'), (self.remote, 'direct')):
                result = await client.get(url + '/redirect')
                self.assertEqual(result.json()['choices'][0]['message']['content'], expected)

    async def test_llm_and_embedding_follow_each_new_request(self):
        profile = {'endpoint': self.remote + '/v1/chat/completions', 'model': 'fixture', 'apiKey': 'fixture-secret'}
        for server, expected in ((self.proxy_a, 'proxy-a'), (None, 'direct'), (self.proxy_b, 'proxy-b')):
            self.route(server)
            progress = {}
            response = await review_llm.chat(profile, [], lambda: False, progress=lambda **kw:progress.update(kw))
            self.assertEqual(response, expected)
            self.assertEqual(progress['networkMode'], 'system_proxy' if server else 'direct')
            result = await asyncio.to_thread(embedding_limits.post, self.remote + '/embeddings', {}, {}, 5, lambda: None)
            self.assertEqual(result.json()['choices'][0]['message']['content'], expected)

    async def test_failed_proxy_does_not_silently_send_direct(self):
        self.route(self.proxy_a)
        # Closed port reserved by a local socket: no external destination.
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            self.proxies['http'] = f'http://127.0.0.1:{unavailable.getsockname()[1]}'
            async with httpx.AsyncClient(transport=network.SystemProxyTransport(), trust_env=False, timeout=2) as client:
                with self.assertRaises(httpx.TransportError): await client.get(self.remote)
        self.assertEqual(self.direct.hits, [])

    async def test_proxy_diagnostics_do_not_expose_proxy_credentials(self):
        exc = httpx.ProxyError('http://private-user:private-password@proxy.invalid')
        failure = review_llm.ConnectionFailure(exc, 'https://provider.test/v1', 'connecting', 1, 0, 0, 'system_proxy')
        self.assertIn('系统代理', str(failure))
        self.assertNotIn('private-', str(failure) + json.dumps(failure.diagnostics))


class RoutingTests(unittest.TestCase):
    def test_all_loopback_forms_bypass_even_with_system_proxy(self):
        with patch('urllib.request.getproxies', return_value={'http': 'http://proxy.test:8000'}):
            for host in ('localhost', 'localhost.', 'api.localhost', '127.0.0.1', '127.2.3.4', '[::1]', '[::ffff:127.0.0.1]'):
                self.assertIsNone(network.system_proxy(f'http://{host}:1234/v1'))

    def test_system_bypass_and_scheme_specific_proxy(self):
        with patch('urllib.request.getproxies', return_value={'https': 'http://proxy.test:8000'}), patch('urllib.request.proxy_bypass', return_value=False):
            self.assertEqual(network.system_proxy('https://provider.test'), 'http://proxy.test:8000')
            self.assertIsNone(network.system_proxy('http://provider.test'))
        with patch('urllib.request.proxy_bypass', return_value=True):
            self.assertIsNone(network.system_proxy('https://provider.test'))


if __name__ == '__main__': unittest.main()
