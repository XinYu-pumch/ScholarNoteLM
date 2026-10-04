"""Bounded feedback control; provider quotas remain the limiter's responsibility."""
import math, random, time

RETRY_BASE_SECONDS=2
RETRY_CAP_SECONDS=60
OBSERVATION_SECONDS=10

class Controller:
    def __init__(self, cfg, clock=time.monotonic):
        self.cfg=cfg;self.clock=clock;self.target=2;self.batch=32
        self.failures=0;self.retry_at=0;self.reason='';self.recovering=False;self.healthy=0
        self.started=clock();self.samples=[];self.baseline=None;self.quota_wait=False

    def failed(self, error):
        self.failures+=1;self.healthy=0;self.target=1;self.batch=max(1,self.batch//2)
        self.reason=error.kind;self.recovering=True
        delay=max(error.retry_after, min(RETRY_CAP_SECONDS,RETRY_BASE_SECONDS*2**min(self.failures-1,6))*random.uniform(1,1.15))
        self.retry_at=max(self.retry_at,self.clock()+delay)
        self.samples=[];self.baseline=None;self.started=self.clock()
        return delay

    def success(self, seconds, tokens):
        now=self.clock()
        if self.recovering:
            self.healthy+=1
            if self.healthy<3:return
            self.recovering=False;self.failures=0;self.reason='';self.retry_at=0
            self.started=now;self.samples=[];self.quota_wait=False
        self.samples.append((max(.001,seconds),max(1,tokens)))
        elapsed=now-self.started
        if elapsed<OBSERVATION_SECONDS or len(self.samples)<4:return
        latency=sum(s for s,_ in self.samples)/len(self.samples)
        volume=sum(t for _,t in self.samples);per_request=volume/len(self.samples)
        throughput=volume/elapsed
        desired=max(1,min(16,math.ceil(min(self.cfg['rpm']/60,self.cfg['tpm']/60/per_request)*latency*1.25)))
        # Compare only windows supplied with work. Quota waiting is not congestion.
        congested=(not self.quota_wait and self.baseline and latency>self.baseline[0]*1.35 and throughput<self.baseline[1]*1.1)
        if congested:
            self.target=max(1,self.target-1);self.batch=max(1,self.batch//2);self.baseline=None
        else:
            self.target=min(self.target+1,desired)
            if not self.quota_wait:
                self.baseline=(latency,throughput)
                self.batch=min(32,max(self.batch+1,self.batch*2))
        self.samples=[];self.started=now;self.quota_wait=False

    def state(self):
        if self.clock()<self.retry_at:
            return {'network':'waiting_network','timeout':'waiting_network','rate_limit':'waiting_rate_limit'}.get(self.reason,'waiting_service')
        return 'recovering' if self.recovering else 'running'
