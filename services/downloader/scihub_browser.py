"""Lazy batch-owned Chromium sidecar. JSON control only; bodies stay in temp files.

Each article/pass gets a fresh ephemeral context. No HTTP fallback, persistent
profile, credentials or signed URLs are logged. Cancellation closes the context;
an unresponsive sidecar is reaped together with its Chromium process group.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import uuid

TRANSPORT = 'playwright-chromium'
MAX_BYTES = 250 * 1024 * 1024

class BrowserError(RuntimeError):
    def __init__(self, kind, message, metrics=None):
        super().__init__(message)
        self.kind = kind
        self.metrics = metrics or {}

class BrowserPool:
    def __init__(self, root=None, temp_parent=None):
        self.root = Path(root or os.environ.get('SCHOLARNOTELM_ROOT', Path(__file__).resolve().parents[2]))
        self.temp_parent = Path(temp_parent or self.root/'tmp')
        self.process = None
        self.browser_pid = None
        self.directory = None
        self.reader = None
        self.pending = {}
        self.sequence = 0
        self.start_lock = asyncio.Lock()
        self.close_lock = asyncio.Lock()
        self.failure = None
        self.closed = False
        self.version = ''

    def session(self, **kwargs):return BrowserSession(self)

    async def start(self):
        async with self.start_lock:
            if self.failure:raise self.failure
            if self.closed:raise BrowserError('browser_error','Chromium 批次会话已关闭')
            if self.process:return
            node=self.root/('runtimes/node/node.exe' if os.name=='nt' else 'runtimes/node/bin/node')
            if not node.is_file():raise BrowserError('browser_unavailable','缺少项目内 Node 运行时')
            self.temp_parent.mkdir(parents=True,exist_ok=True)
            self.directory=Path(tempfile.mkdtemp(prefix='scihub-browser-',dir=self.temp_parent))
            env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':str(self.root/'runtimes/playwright'),'TMPDIR':str(self.directory),'TMP':str(self.directory),'TEMP':str(self.directory)}
            # The pending spawn must be joined on cancellation; otherwise a late
            # child can outlive its owner before a handle has been recorded.
            spawn=asyncio.create_task(asyncio.create_subprocess_exec(str(node),str(Path(__file__).with_suffix('.mjs')),str(self.directory),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
                env=env,limit=1024*1024,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True})))
            try:self.process=await asyncio.shield(spawn)
            except BaseException:
                self.process=await spawn
                await self.close()
                raise
            self.reader=asyncio.create_task(self._read())

    async def _read(self):
        try:
            while line:=await self.process.stdout.readline():
                value=json.loads(line)
                if value.get('event')=='browser':
                    self.browser_pid=value['pid'];self.version=value['version'];continue
                future=self.pending.pop(value['id'],None)
                if future and not future.done():
                    if 'error' in value:future.set_exception(BrowserError(value['kind'],value['error'],value.get('metrics')))
                    else:future.set_result(value['data'])
        except (ValueError,KeyError,asyncio.CancelledError):pass
        finally:
            self.failure=BrowserError('browser_error','Chromium 浏览器进程异常退出或通信中断')
            for future in self.pending.values():
                if not future.done():future.set_exception(self.failure)
            self.pending.clear()
            # BrowserServer uses a separate process group on POSIX.
            self._kill_browser()

    async def call(self, **args):
        await self.start()
        self.sequence+=1;key=self.sequence
        future=asyncio.get_running_loop().create_future();self.pending[key]=future
        try:
            self.process.stdin.write((json.dumps({'id':key,**args})+'\n').encode())
            await self.process.stdin.drain()
            return await future
        except (BrokenPipeError,ConnectionResetError):
            raise BrowserError('browser_error','Chromium 浏览器通信中断') from None
        finally:self.pending.pop(key,None)

    def _kill_browser(self):
        if not self.browser_pid:return
        pid,self.browser_pid=self.browser_pid,None
        if os.name=='nt':
            # Chromium may survive a crashed Node sidecar; its PID is reported
            # by the owned BrowserServer, never discovered by process name.
            try:
                subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=2)
            except (OSError,subprocess.TimeoutExpired):pass
        else:
            try:os.killpg(pid,signal.SIGKILL)
            except ProcessLookupError:pass

    async def close_session(self, key):
        if not self.process or self.closed:return
        try:
            async with asyncio.timeout(1.5):await self.call(op='close',session=key)
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception:
            # If closing a context stalls, keeping this batch browser alive is unsafe.
            await self.close()

    async def close(self):
        async with self.close_lock:
            if self.closed:return
            self.closed=True
            if self.process:
                if self.process.stdin:self.process.stdin.close()
                try:await asyncio.wait_for(self.process.wait(),2)
                except TimeoutError:
                    if os.name=='nt':
                        killer=await asyncio.create_subprocess_exec('taskkill','/PID',str(self.process.pid),'/T','/F',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
                        try:await asyncio.wait_for(killer.wait(),2)
                        except TimeoutError:killer.kill()
                    else:
                        try:os.killpg(self.process.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                    self._kill_browser()
                    await self.process.wait()
                self._kill_browser()
            if self.reader:
                await self.reader
            if self.directory:shutil.rmtree(self.directory,ignore_errors=True)

class BrowserSession:
    transport = TRANSPORT
    def __init__(self,pool,owned=False):
        self.pool=pool;self.owned=owned;self.key=uuid.uuid4().hex
    async def __aenter__(self):return self
    async def __aexit__(self,*args):
        await self.pool.close_session(self.key)
        if self.owned:await self.pool.close()
    async def protocol(self,url,method,payload,timeout):
        try:
            async with asyncio.timeout(timeout):
                data=await self.pool.call(op='protocol',session=self.key,url=url,method=method,payload=payload,timeout=timeout)
                return SimpleNamespace(content=data['text'].encode(),**data)
        except BaseException:
            await self.pool.close_session(self.key)
            self.key=uuid.uuid4().hex
            raise
    async def remember_cookies(self):
        try:
            async with asyncio.timeout(1):await self.pool.call(op='rememberCookies',session=self.key)
        except BaseException:
            await self.pool.close_session(self.key)
            self.key=uuid.uuid4().hex
            raise
    async def get(self,url,timeout,allow_redirects=True,role='entry'):
        try:
            # Includes lazy startup, DOM rendering, complete response/download and IPC.
            async with asyncio.timeout(timeout):
                data=await self.pool.call(op='get',session=self.key,url=url,timeout=timeout,role=role)
                path=Path(data.pop('body'))
                if path.parent!=self.pool.directory or path.is_symlink():raise BrowserError('browser_error','浏览器响应路径无效')
                try:
                    if path.stat().st_size>MAX_BYTES:raise BrowserError('response_too_large','浏览器响应超过 250 MiB')
                    content=path.read_bytes()
                finally:path.unlink(missing_ok=True)
                return SimpleNamespace(content=content,text=content.decode('utf8',errors='replace') if data['method']=='browser-rendered-dom' else '',**data)
        except BaseException:
            await self.pool.close_session(self.key)
            # Closing an interrupted context must not poison later mirror
            # attempts in this logical article session. A crashed pool still
            # fails explicitly; there is no browser restart or HTTP fallback.
            self.key=uuid.uuid4().hex
            raise

def session(**kwargs):
    pool=BrowserPool()
    result=pool.session();result.owned=True
    return result
