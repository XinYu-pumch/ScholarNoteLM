"""Quota-driven corpus embedding, durable cache, bounded adaptive concurrency.

Auto mode uses a matching tokenizer plus margin, otherwise UTF-8 byte budgets.
Explicit conservative mode still reserves 8192 tokens per text. Actual usage
releases excess reservations and drives concurrency, never the reservation size.
No source text is truncated or merged. Publication remains in vector_service.
"""
import concurrent.futures,json,math,struct,time,threading,hashlib
import embedding_limits as limits
import vector_chunks as chunks
import corpus_files as files
import artifact_state
from collections import deque
from itertools import islice
from embedding_controller import Controller, MAX_CONCURRENCY


def populate(e,cfg,pmids,check,notify,out,budget_mode="conservative",on_ready=lambda p:None):
    import vector_service as v
    pid=v.cache_profile(e,cfg);docs={d['pmid']:d for d in chunks.documents(e,pid) if d['pmid'] in pmids}
    wanted={};owners={};epochs={p:d['metadata'].get('rebuildEpoch',0) for p,d in docs.items()}
    with chunks.connect(e) as db:
        for p,d in docs.items():
            for record in chunks.records_for(db,d['version'],d['metadata']):
                text=chunks.embedding_text(record);h=chunks.digest(text)
                wanted[h]=text;owners.setdefault(h,set()).add(p)
        cached={r[0] for r in db.execute('SELECT input_hash FROM embeddings WHERE profile=?',(pid,))}
        # Identical bodies may share vectors, but each document must own its cache entry.
        for h in wanted.keys()&cached:
            db.executemany('INSERT OR IGNORE INTO embedding_owners VALUES(?,?,?)',[(pid,h,p) for p in owners[h]])
    remaining={p:set() for p in docs}
    for h,ps in owners.items():
        if h not in cached:
            for p in ps:remaining[p].add(h)
    for p,missing in remaining.items():
        if not missing:on_ready(p)
    pending=[(h,t) for h,t in wanted.items() if h not in cached]
    if not pending:notify({'total':len(wanted),'completed':len(wanted),'requests':0});return
    def save(group,values):
        became_ready=set()
        with files.lock(e),chunks.connect(e) as db:
            current=files.current(e) or set()
            dim=len(values[0]);old=db.execute('SELECT dimension FROM profiles WHERE id=?',(pid,)).fetchone()
            if old and old[0]!=dim:raise ValueError('模型向量维度变化，请更改模型版本标识')
            db.execute('INSERT OR IGNORE INTO profiles VALUES(?,?,?)',(pid,dim,json.dumps(v.public(cfg))))
            for (h,_),vector in zip(group,values):
                valid=[p for p in owners[h] if p in current and artifact_state.epoch(e,p)==epochs[p]]
                if not valid:raise ValueError('材料已移出或重新纳入，请重新启动索引')
                if len(vector)!=dim:raise ValueError('向量维度不一致')
                db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?)',(pid,h,dim,struct.pack('<'+'f'*dim,*vector)))
                db.executemany('INSERT OR IGNORE INTO embedding_owners VALUES(?,?,?)',[(pid,h,p) for p in valid])
        for h,_ in group:
            for p in owners[h]:
                remaining[p].discard(h)
                if not remaining[p]:became_ready.add(p)
        for p in became_ready:on_ready(p)
    return run_inputs(e,cfg,pending,check,notify,out,save,budget_mode,total=len(wanted),cached=len(wanted)-len(pending))


def run_inputs(e,cfg,pending,check,notify,out,save,budget_mode='conservative',total=None,cached=0):
    import vector_service as v
    total=total if total is not None else len(pending)
    if cfg['tpm']<8192:raise ValueError('自动调度要求 TPM 至少为 8192，以预留一个完整文本块')
    costs=[8192]*len(pending)
    if budget_mode=='auto':
        if verified_tokenizer(e,cfg):budget_mode='verified'
        else:
            from embedding_token_budget import jina_costs
            costs=jina_costs(e.ROOT,cfg,[text for _,text in pending],check)
            budget_mode='tokenizer' if costs is not None else 'bytes'
            if costs is None:costs=[limits.estimate([text]) for _,text in pending]
    if budget_mode=='verified':
        from tokenizers import Tokenizer
        folder=e.ROOT/'cache/embedding-tokenizers/bge-m3'
        metadata=json.loads((folder/'verified.json').read_text());path=folder/'tokenizer.json'
        if metadata['model']!=cfg['model'] or metadata.get('modelRevision','')!=cfg.get('modelRevision','') or metadata['endpoint']!=v.endpoint(cfg) or hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['sha256']:
            raise ValueError('Tokenizer 与已验证的模型配置不匹配')
        tokenizer=Tokenizer.from_file(str(path));tokenizer.no_truncation();tokenizer.no_padding()
        counts=[len(value.ids) for value in tokenizer.encode_batch([text for _,text in pending])]
        if any(n>8192 for n in counts):raise ValueError('文本块实际 token 超过 8192，未截断或跳过，请调整分块')
        costs=[math.ceil(n*1.02)+2 for n in counts]
    if any(cost>cfg['tpm'] for cost in costs):raise ValueError('单个文本块的预留 token 超过 TPM 设置')
    stopped=threading.Event()
    def checked():
        if stopped.is_set():raise InterruptedError('调度已停止')
        check()
    limiter=limits.Limiter(e.ROOT,cfg,checked);start=time.time();event_lock=threading.Lock()
    stats={'total':total,'completed':cached,'requests':0,'actualTokens':0,'retries':0,'maxConcurrency':MAX_CONCURRENCY,'tokenBudget':budget_mode,'reservationPerChunk':8192 if budget_mode=='conservative' else None}
    def response(event):
        # Persist only timing/usage, never headers, credentials or request bodies.
        with event_lock:
            with (out/'embedding-requests.jsonl').open('a') as f:f.write(json.dumps(event)+'\n')
            stats['requests']+=1
            usage=event.get('usage') or {}
            actual=usage.get('prompt_tokens',usage.get('total_tokens',0)) if isinstance(usage,dict) else 0
            actual=actual if type(actual) is int and actual>=0 else 0
            stats['actualTokens']+=actual
            if budget_mode in ('verified','tokenizer') and actual>event['reserved']:
                raise ValueError('实际 usage 超过 Tokenizer 预留，请重新校准；已完成结果保留')
    queue=deque(zip(pending,costs));running={};control=Controller(cfg);last_notify=0
    control.prime(sum(costs)/max(1,len(costs)))
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENCY)
    try:
        while queue or running:
            checked();quota_wait=False
            while queue and len(running)<control.target and time.monotonic()>=control.retry_at:
                # Recover using a single small probe; every retry reserves quota anew.
                size=1 if control.recovering else control.batch
                candidates=list(islice(queue,size))
                admission=limiter.reserve_batch(len(candidates),costs=[cost for _,cost in candidates])
                if not admission:quota_wait=True;control.quota_wait=True;break
                reservation,count=admission;batch=[queue.popleft() for _ in range(count)]
                group=[item for item,_ in batch];reserved=sum(cost for _,cost in batch)
                feedback={}
                def responded(event,feedback=feedback):
                    feedback.update(event);response(event)
                future=pool.submit(v.embed,[text for _,text in group],{**cfg,'batchSize':control.max_batch},attempts=1,check=checked,root=e.ROOT,reservation=reservation,reserved_tokens=reserved,on_response=responded)
                running[future]=(batch,time.monotonic(),control.failures,feedback)
            ready,_=concurrent.futures.wait(running,timeout=.05,return_when=concurrent.futures.FIRST_COMPLETED) if running else ([],[])
            for future in ready:
                batch,began,generation,feedback=running.pop(future)
                try:values=future.result()
                except limits.TransientError as error:
                    queue.extendleft(reversed(batch));stats['retries']+=1
                    delay=control.failed(error)
                    # Share cooldown with other indexing jobs and question embeddings.
                    limiter.cooldown(delay)
                    continue
                group=[item for item,_ in batch]
                if len(values)!=len(group):raise ValueError('Embedding 返回数量不匹配')
                save(group,values);stats['completed']+=len(group)
                # Responses sent before a failure must not close the recovery circuit.
                usage=feedback.get('usage') or {}
                actual=usage.get('prompt_tokens',usage.get('total_tokens')) if isinstance(usage,dict) else None
                tokens=actual if type(actual) is int and actual>0 else sum(cost for _,cost in batch)
                if generation==control.failures:control.success(time.monotonic()-began,tokens,len(batch))
            now=time.time();state=control.state()
            if state=='running' and quota_wait:state='waiting_quota'
            if now-last_notify>=1 or not queue and not running:
                with event_lock:
                    stats.update(concurrency=control.target,batchLimit=control.batch,inFlight=len(running),elapsed=round(now-start,2),waitingForQuota=quota_wait,state=state,nextRetryAt=now+max(0,control.retry_at-time.monotonic()),consecutiveFailures=control.failures)
                    snapshot=dict(stats)
                notify(snapshot);last_notify=now
            if not running and queue:limits.wait(.05,checked)
    finally:
        stopped.set()
        for future in running:future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)
    notify({**stats,'completed':total,'state':'complete','inFlight':0,'elapsed':round(time.time()-start,2)})


def verified_tokenizer(e,cfg):
    """A changed provider/model never inherits another model's calibration."""
    import vector_service as v
    folder=e.ROOT/'cache/embedding-tokenizers/bge-m3'
    try:
        metadata=json.loads((folder/'verified.json').read_text());path=folder/'tokenizer.json'
        return (metadata['model']==cfg['model'] and metadata.get('modelRevision','')==cfg.get('modelRevision','')
                and metadata['endpoint']==v.endpoint(cfg) and hashlib.sha256(path.read_bytes()).hexdigest()==metadata['sha256'])
    except (OSError,ValueError,KeyError,TypeError):return False
