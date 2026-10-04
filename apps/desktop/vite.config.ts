import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import {researchBridge,autoMesh} from './research-bridge';
import { fileURLToPath } from 'node:url';
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import type { IncomingMessage, ServerResponse } from 'node:http';

const prototypeDir = fileURLToPath(new URL('../../data/prototype/', import.meta.url));
async function prototypeStorage(req: IncomingMessage, res: ServerResponse, next: () => void) {
  if (req.url !== '/__prototype/state' && req.url !== '/__prototype/export') return next();
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  const origin = req.headers.origin;
  if (origin && !/^https?:\/\/(127\.0\.0\.1|localhost):\d+$/.test(origin)) { res.statusCode = 403; res.end('{}'); return; }
  try {
    if (req.url === '/__prototype/export') {
      if (req.method !== 'POST') { res.statusCode = 405; res.end('{}'); return; }
      let body = '';
      for await (const part of req) { body += part; if (body.length > 5_000_000) { res.statusCode = 413; res.end('{}'); return; } }
      const value = JSON.parse(body);
      const name = typeof value.name === 'string' ? value.name.replace(/[\\/:*?"<>|\x00-\x1f]/g, '').slice(0, 120) : '';
      if (!name.endsWith('.md') || typeof value.content !== 'string') { res.statusCode = 400; res.end('{}'); return; }
      await mkdir(prototypeDir + 'exports', { recursive: true });
      const path = prototypeDir + 'exports/' + Date.now() + '-' + name;
      await writeFile(path, value.content, { flag: 'wx' });
      res.end(JSON.stringify({ path }));
      return;
    }
    if (req.method === 'GET') {
      let value = 'null';
      try { value = await readFile(prototypeDir + 'state.json', 'utf8'); } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
      res.end(value);
    } else if (req.method === 'PUT') {
      let body = '';
      for await (const part of req) { body += part; if (body.length > 5_000_000) { res.statusCode = 413; res.end('{}'); return; } }
      const value = JSON.parse(body);
      if (value.version !== 1 || !Array.isArray(value.projects)) { res.statusCode = 400; res.end('{}'); return; }
      await mkdir(prototypeDir, { recursive: true });
      const temp = prototypeDir + `state-${crypto.randomUUID()}.tmp`;
      await writeFile(temp, JSON.stringify(value, null, 2));
      await rename(temp, prototypeDir + 'state.json');
      res.end('{"ok":true}');
    } else { res.statusCode = 405; res.end('{}'); }
  } catch { res.statusCode = 500; res.end('{"error":"Unable to access prototype state"}'); }
}

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react(), { name:'local-research-engine', configureServer(server) { server.middlewares.use(researchBridge); const child=autoMesh(); const timer=setInterval(autoMesh,3600000); server.httpServer?.once('close',()=>{clearInterval(timer);child.kill();}); }, configurePreviewServer(server) { server.middlewares.use(researchBridge); } }, { name: 'local-prototype-storage', configureServer(server) { server.middlewares.use(prototypeStorage); }, configurePreviewServer(server) { server.middlewares.use(prototypeStorage); } }],
  cacheDir: '../../cache/vite',
  clearScreen: false,
  server: { host: '127.0.0.1', port: 1420, strictPort: true },
  build: { outDir: '../../dist/ui', emptyOutDir: true, target: 'safari15' },
});
