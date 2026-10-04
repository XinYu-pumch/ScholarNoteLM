import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import net from 'node:net';
import { mkdirSync } from 'node:fs';
const root = fileURLToPath(new URL('..', import.meta.url));
const dev = process.argv[2] === 'dev';
const cli = path.join(root, 'node_modules/@tauri-apps/cli/tauri.js');
const windows = process.platform === 'win32';
const env = {
  ...process.env, SCHOLARNOTELM_ROOT: root,
  SCHOLARNOTELM_DEV: dev ? '1' : '0',
  PATH: [path.dirname(process.execPath), path.join(root, 'cache/cargo/bin'), process.env.PATH].join(path.delimiter),
  CARGO_HOME: path.join(root, 'cache/cargo'), RUSTUP_HOME: path.join(root, 'runtimes/rust'),
  CARGO_TARGET_DIR: path.join(root, 'cache/tauri-target'), npm_config_cache: path.join(root, 'cache/npm'),
  TMPDIR: path.join(root, 'tmp'), TEMP: path.join(root, 'tmp'), TMP: path.join(root, 'tmp'),
};
mkdirSync(env.TMPDIR, { recursive: true });
if (dev) {
  // Do not attach a desktop window to an unrelated or stale Vite process.
  const free = await new Promise(resolve => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(1420, '127.0.0.1', () => server.close(() => resolve(true)));
  });
  if (!free) {
    console.error('1420 端口已被占用：如果开发版已打开，请直接使用；否则先退出旧的开发预览。');
    process.exit(1);
  }
}
const child = spawn(process.execPath, [cli, ...process.argv.slice(2)], {
  cwd: path.join(root, 'apps/desktop'), stdio: 'inherit', env,
  detached: !windows,
});
let stopping = false;
function stop(signal) {
  if (stopping) return;
  stopping = true;
  if (windows) spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  else { try { process.kill(-child.pid, signal); } catch (error) { if (!['ESRCH','EPERM'].includes(error.code)) throw error; } }
}
process.on('SIGINT', () => stop('SIGINT'));
process.on('SIGTERM', () => stop('SIGTERM'));
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => {
  // Tauri owns its Vite child; clean up its process group if it left a server behind.
  stop('SIGTERM');
  process.exit(code ?? (signal === 'SIGINT' || stopping ? 0 : 1));
});
