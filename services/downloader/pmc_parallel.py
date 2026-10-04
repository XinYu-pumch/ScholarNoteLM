"""Two opposing PMC queues, with exclusive article claims and immediate fallback."""
import asyncio
import json
import re
import time

S3 = 'pmc_s3'
GETPDF = 'europe_pmc_getpdf'


def normalize_pmcid(value):
    match = re.fullmatch(r'(?:PMC)?([0-9]+)', str(value or '').strip(), re.I)
    return 'PMC' + str(int(match[1])) if match and int(match[1]) > 0 else None


async def run(engine, batch, cfg, attempt):
    """Each source claims an article once per cycle; interrupted claims are resumable.

    Only records already carrying a valid PMCID enter this stage. Other records
    remain untouched for the DOI-based sources; no per-PMID lookup is performed.
    A source may retire only when no claim, including the other source's, can
    make more work eligible. No article is downloaded by both at the same time.
    """
    bid = batch['id']
    items = {i['pmid']: i for i in engine.rows(
        "SELECT * FROM items WHERE batch=? AND state IN ('queued','running')", (bid,))
        if normalize_pmcid(json.loads(i['paper']).get('pmcid'))}
    completed = {p: set(engine.progress(bid, p).get('completedStages', [])) for p in items}
    active = set()
    condition = asyncio.Condition()
    runs = {}
    if not items:
        return
    started = time.monotonic()
    with engine.db() as db:
        pair_id = db.execute("INSERT INTO stage_runs(batch,stage,started,state) VALUES(?,'pmc_parallel',?,'running')",
                             (bid, time.time())).lastrowid
    pair_state = 'completed'

    def claim(stage):
        eligible = []
        for p, item in items.items():
            if p in active or item['state'] in ('success', 'skipped') or stage in completed[p]:
                continue
            pmcid = normalize_pmcid(json.loads(item['paper']).get('pmcid'))
            if not pmcid:
                continue
            eligible.append((int(pmcid[3:]), int(p), item))
        if not eligible:
            return None
        eligible.sort(key=lambda v: v[:2], reverse=stage == GETPDF)
        item = eligible[0][2]
        active.add(item['pmid'])
        if stage not in runs:
            with engine.db() as db:
                rid = db.execute("INSERT INTO stage_runs(batch,stage,started,state) VALUES(?,?,?,'running')",
                                 (bid, stage, time.time())).lastrowid
            runs[stage] = (rid, time.monotonic())
            engine.event(batch, '', stage, '并行来源开始',
                         direction='ascending' if stage == S3 else 'descending')
        return item

    async def worker(stage):
        while True:
            async with condition:
                while (item := claim(stage)) is None:
                    if not active:
                        return
                    await condition.wait()
            p = item['pmid']
            try:
                await attempt(item, 0, stage)
            finally:
                async with condition:
                    items[p] = engine.one('SELECT * FROM items WHERE batch=? AND pmid=?', (bid, p))
                    completed[p] = set(engine.progress(bid, p).get('completedStages', []))
                    active.remove(p)
                    condition.notify_all()
            # Also yield when a source immediately reports an absent record.
            await asyncio.sleep(0)

    async def source(stage, workers):
        state = 'completed'
        try:
            async with asyncio.TaskGroup() as group:
                for _ in range(min(workers, len(items))):
                    group.create_task(worker(stage))
        except BaseException:
            state = 'interrupted'
            raise
        finally:
            if stage in runs:
                rid, begin = runs[stage]
                elapsed = time.monotonic() - begin
                engine.execute('UPDATE stage_runs SET elapsed=?,state=? WHERE id=?', (elapsed, state, rid))
                engine.event(batch, '', stage, '并行来源结束', wallSeconds=round(elapsed, 3), state=state)

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(source(S3, cfg['pmcConcurrency']))
            group.create_task(source(GETPDF, cfg['europePmcConcurrency']))
    except BaseException:
        pair_state = 'interrupted'
        raise
    finally:
        elapsed = time.monotonic() - started
        engine.execute('UPDATE stage_runs SET elapsed=?,state=? WHERE id=?', (elapsed, pair_state, pair_id))
        engine.event(batch, '', 'pmc_parallel', 'PMC 双路阶段结束', wallSeconds=round(elapsed, 3), state=pair_state)
