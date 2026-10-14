"""Bounded feedback control; provider quotas remain the limiter's responsibility."""
import math, random, time

RETRY_BASE_SECONDS=2
RETRY_CAP_SECONDS=60
OBSERVATION_SECONDS=10
MAX_CONCURRENCY=64

class Controller:
    def __init__(self, cfg, clock=time.monotonic):
        self.cfg=cfg;self.clock=clock;self.target=2;self.batch=32
        from embedding_providers import is_jina
        self.max_batch=128 if is_jina(cfg) else 32
        self.failures=0;self.retry_at=0;self.reason='';self.recovering=False;self.healthy=0
        self.started=clock();self.samples=[];self.quota_wait=False

    def prime(self, tokens_per_item):
        # About one RPM slot's worth of TPM per request. The admission ledger
        # independently enforces both budgets and packs heterogeneous inputs.
        self.batch=max(1,min(self.max_batch,math.ceil(self.cfg['tpm']/self.cfg['rpm']/max(1,tokens_per_item))))

    def failed(self, error):
        self.failures+=1;self.healthy=0;self.target=1;self.batch=max(1,self.batch//2)
        self.reason=error.kind;self.recovering=True
        delay=max(error.retry_after, min(RETRY_CAP_SECONDS,RETRY_BASE_SECONDS*2**min(self.failures-1,6))*random.uniform(1,1.15))
        self.retry_at=max(self.retry_at,self.clock()+delay)
        self.samples=[];self.started=self.clock()
        return delay

    def success(self, seconds, tokens, count=1):
        now=self.clock()
        if self.recovering:
            self.healthy+=1
            if self.healthy<3:return
            self.recovering=False;self.failures=0;self.reason='';self.retry_at=0
            self.started=now;self.samples=[];self.quota_wait=False
        self.samples.append((max(.001,seconds),max(1,tokens),max(1,count)))
        elapsed=now-self.started
        if elapsed<OBSERVATION_SECONDS or len(self.samples)<4:return
        latency=sum(s for s,_,_ in self.samples)/len(self.samples)
        volume=sum(t for _,t,_ in self.samples);items=sum(n for _,_,n in self.samples)
        tokens_per_item=volume/items
        self.prime(tokens_per_item)
        per_request=tokens_per_item*self.batch
        desired=max(1,min(MAX_CONCURRENCY,math.ceil(min(self.cfg['rpm']/60,self.cfg['tpm']/60/per_request)*latency*1.15)))
        # Slow *successful* requests need more overlap. Latency alone cannot tell
        # network delay from overload; only explicit failures trigger backoff.
        self.target=min(self.target*2,desired)
        self.samples=[];self.started=now;self.quota_wait=False

    def state(self):
        if self.clock()<self.retry_at:
            return {'network':'waiting_network','timeout':'waiting_network','rate_limit':'waiting_rate_limit'}.get(self.reason,'waiting_service')
        return 'recovering' if self.recovering else 'running'
