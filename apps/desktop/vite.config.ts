import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import {researchBridge,autoMesh} from './research-bridge';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [react(), { name:'local-research-engine', configureServer(server) { server.middlewares.use(researchBridge); const child=autoMesh(); const timer=setInterval(autoMesh,3600000); server.httpServer?.once('close',()=>{clearInterval(timer);child.kill();}); }, configurePreviewServer(server) { server.middlewares.use(researchBridge); } }],
  cacheDir: '../../cache/vite',
  clearScreen: false,
  server: { host: '127.0.0.1', port: 1420, strictPort: true },
  build: { outDir: '../../dist/ui', emptyOutDir: true, target: 'safari15' },
});
