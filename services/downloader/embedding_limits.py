"""Cross-process embedding RPM/estimated-TPM reservations, with shared cooldowns."""
import asyncio,email.utils,sqlite3,time,uuid
from contextlib import contextmanager
import retrieval_settings as settings

WINDOW_SECONDS=61  # Cover dispatch/clock jitter at the provider's 60-second boundary.

def estimate(texts):
    # Conservative byte estimate, not the provider's tokenizer. Never truncate input.
    return sum(len(t.encode('utf-8'))+8 for t in texts)
def wait(seconds,check):
    deadline=time.monotonic()+max(0,seconds)
    while time.monotonic()<deadline:
        check();time.sleep(min(.15,max(0,deadline-time.monotonic())))
class TransientError(ValueError):
    def __init__(self, message, *, kind, retry_after=0):
        super().__init__(message)
        self.kind=kind;self.retry_after=retry_after

class Limiter:
    def __init__(self,root,cfg,check=lambda:None):
        self.check=check;self.cfg={'rpm':cfg.get('rpm',60),'tpm':cfg.get('tpm',120000)};self.key=settings.fingerprint(cfg)
        self.path=root/'data/research/embedding-rate.sqlite3';self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,service TEXT,at REAL,tokens INTEGER); CREATE INDEX IF NOT EXISTS recent ON requests(service,at); CREATE TABLE IF NOT EXISTS gates(service TEXT PRIMARY KEY,until REAL);')
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=10)
        try:
            with c:yield c
        finally:c.close()
    def acquire(self,tokens):
        if tokens>self.cfg['tpm']:raise ValueError('单个文本的估算 token 数超过 TPM 限速设置，请提高 TPM；文本块未截断')
        while True:
            self.check();now=time.time();delay=0
            with self.db() as c:
                c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM requests WHERE at<=?',(now-WINDOW_SECONDS,))
                rows=c.execute('SELECT at,tokens FROM requests WHERE service=? ORDER BY at',(self.key,)).fetchall()
                gate=c.execute('SELECT until FROM gates WHERE service=?',(self.key,)).fetchone()
                if gate:delay=max(delay,gate[0]-now)
                if rows:
                    delay=max(delay,rows[-1][0]+60/self.cfg['rpm']-now)
                    remaining=sum(t for _,t in rows);count=len(rows)
                    for at,t in rows:
                        if count<self.cfg['rpm'] and remaining+tokens<=self.cfg['tpm']:break
                        delay=max(delay,at+WINDOW_SECONDS-now);count-=1;remaining-=t
                if delay<=0:
                    ident=uuid.uuid4().hex;c.execute('INSERT INTO requests VALUES(?,?,?,?)',(ident,self.key,now,tokens));return ident
            wait(min(delay,.1),self.check)
    def reserve_batch(self,max_items,tokens_per_item=8192,costs=None):
        """Nonblocking atomic admission; let a scheduler pack the remaining budget."""
        self.check();now=time.time()
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM requests WHERE at<=?',(now-WINDOW_SECONDS,))
            rows=c.execute('SELECT at,tokens FROM requests WHERE service=? ORDER BY at',(self.key,)).fetchall()
            gate=c.execute('SELECT until FROM gates WHERE service=?',(self.key,)).fetchone()
            if gate and gate[0]>now:return None
            if len(rows)>=self.cfg['rpm'] or (rows and rows[-1][0]+60/self.cfg['rpm']>now):return None
            remaining=self.cfg['tpm']-sum(t for _,t in rows);count=0;reserved=0
            for cost in (costs[:max_items] if costs is not None else [tokens_per_item]*max_items):
                if not isinstance(cost,int) or cost<=0:raise ValueError('无效 token 预算')
                if reserved+cost>remaining:break
                count+=1;reserved+=cost
            if not count:return None
            ident=uuid.uuid4().hex
            c.execute('INSERT INTO requests VALUES(?,?,?,?)',(ident,self.key,now,reserved))
            return ident,count
    def mark_dispatched(self,ident):
        # Admission can precede a worker's actual send; never expire that request early.
        now=time.time()
        with self.db() as c:c.execute('UPDATE requests SET at=? WHERE id=?',(now,ident))
        return now
    def reconcile(self,ident,usage):
        if not isinstance(usage,dict):return
        actual=usage.get('prompt_tokens',usage.get('total_tokens'))
        if type(actual) is int and actual>=0:
            with self.db() as c:c.execute('UPDATE requests SET tokens=? WHERE id=?',(actual,ident))
    def cooldown(self,seconds):
        with self.db() as c:c.execute('INSERT INTO gates VALUES(?,?) ON CONFLICT(service) DO UPDATE SET until=MAX(until,excluded.until)',(self.key,time.time()+seconds))

def retry_after(value,fallback):
    try:return max(fallback,float(value))
    except (ValueError,TypeError):
        try:return max(fallback,email.utils.parsedate_to_datetime(value).timestamp()-time.time())
        except (ValueError,TypeError,OverflowError):return fallback

def post(url,headers,payload,timeout,check):
    import httpx
    async def send():
        async with httpx.AsyncClient(timeout=timeout,follow_redirects=False,trust_env=False) as client:
            task=asyncio.create_task(client.post(url,headers=headers,json=payload))
            try:
                while not task.done():
                    check();await asyncio.wait({task},timeout=.15)
                check();return await task
            finally:
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)
    return asyncio.run(send())
