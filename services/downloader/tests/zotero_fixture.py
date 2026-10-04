"""Offline Local API fixture. Never reads a real Zotero library."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from urllib.parse import urlsplit, parse_qs


def parent(key='PARENT01', doi='10.1234/test', **extra):
    return {'key': key, 'data': {'key': key, 'itemType': 'journalArticle', 'DOI': doi, **extra}}


def attachment(key='ATTACH01', parent_key='PARENT01', title='Full Text PDF', **extra):
    return {'key': key, 'data': {'key': key, 'itemType': 'attachment', 'parentItem': parent_key,
            'linkMode': 'imported_url', 'contentType': 'application/pdf', 'title': title,
            'filename': 'main.pdf', 'url': 'https://publisher.example/article/main.pdf?token=PRIVATE', **extra}}


class Fixture:
    def __init__(self):
        self.parents = [parent()]
        self.children = {'PARENT01': [attachment()]}
        self.paths = {}
        self.calls = []
        self.mode = ''
        self.pause = None
        self.page_size = 100
        self.page_failure = False
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                u = urlsplit(self.path); q = parse_qs(u.query)
                fixture.calls.append((u.path, q))
                if fixture.pause:
                    fixture.pause(u.path, q)
                mode = fixture.mode
                if mode in ('403', '404', '501', 'redirect'):
                    self.send_response(302 if mode == 'redirect' else int(mode))
                    self.send_header('Location', 'https://never-visit.example/');self.end_headers();return
                if mode == 'disconnect':
                    self.connection.close();return
                if mode in ('bad-json', 'slow', 'oversize'):
                    self.send_response(200);self.send_header('Total-Results', '1');self.end_headers()
                    try:
                        if mode == 'slow':
                            for _ in range(200):self.wfile.write(b' ');self.wfile.flush();time.sleep(.05)
                        elif mode == 'oversize':self.wfile.write(b' ' * (4*1024*1024+1))
                        else:self.wfile.write(b'{broken')
                    except (BrokenPipeError, ConnectionResetError):pass
                    return
                if u.path.endswith('/file/view/url'):
                    key = u.path.split('/')[-4]
                    if key not in fixture.paths:self.send_response(404);self.end_headers();return
                    payload = fixture.paths[key].as_uri().encode();self.send_response(200)
                else:
                    data = fixture.parents if u.path.endswith('/items/top') else fixture.children.get(u.path.split('/')[-2], [])
                    start = int(q.get('start', [0])[0])
                    if start and fixture.page_failure:self.send_response(500);self.end_headers();return
                    limit = min(fixture.page_size, int(q.get('limit', [100])[0]))
                    payload = json.dumps(data[start:start+limit]).encode();self.send_response(200)
                    self.send_header('Total-Results', str(len(data)));self.send_header('Last-Modified-Version', '1')
                self.send_header('Content-Length', str(len(payload)));self.end_headers()
                try:self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.address = f'127.0.0.1:{self.server.server_port}'
    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
