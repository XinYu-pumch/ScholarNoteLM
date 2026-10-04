"""Bounded last-chance Zotero stage. Supervisor owns all helper lifetimes."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import zotero_local as z

REAP_SECONDS = .5
HELPER = Path(__file__).with_name('zotero_worker.py')


def kill_helper(process):
    if process.returncode is not None:return
    try:
        # This helper never spawns children. POSIX group kill also covers descendants.
        if os.name == 'nt':process.kill()
        else:os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:pass


async def reap_helper(process, seconds=REAP_SECONDS):
    kill_helper(process)
    try:await asyncio.wait_for(process.wait(), max(.001, seconds))
    except TimeoutError:pass  # Kernel I/O failure must not create an unbounded wait.


def dispose_late_spawn(task):
    # If OS process creation itself outlives cancellation, it has received no stdin
    # and cannot query/copy/publish. Dispose of its handle as soon as it arrives.
    if task.cancelled():return
    try:process=task.result()
    except Exception:return
    kill_helper(process)
    asyncio.create_task(reap_helper(process))


async def helper(request, seconds):
    process = spawn = None
    try:
        async with asyncio.timeout(max(.01, seconds - min(REAP_SECONDS, seconds / 4))):
            options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NO_WINDOW}
            spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                sys.executable, str(HELPER), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, **options))
            process = await asyncio.shield(spawn)
            stdout, _ = await process.communicate(json.dumps(request).encode())
            if process.returncode or len(stdout) > 1024 * 1024:
                return {'outcome': 'skipped', 'reason': 'Zotero 辅助进程退出异常'}
            return json.loads(stdout)
    finally:
        cleanup_deadline = time.monotonic() + REAP_SECONDS
        if process is None and spawn is not None:
            try:process = await asyncio.wait_for(asyncio.shield(spawn), REAP_SECONDS)
            except TimeoutError:spawn.add_done_callback(dispose_late_spawn)
        if process is not None:
            await reap_helper(process, cleanup_deadline - time.monotonic())


async def run(e, b, cfg):
    token = e.DB_TIMEOUT.set(.2)
    try:
        try:
            await _run(e, b, cfg)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            # Optional-source failures must not pause the batch.
            try:e.event(b, '', 'zotero', 'Zotero 阶段跳过', error=type(ex).__name__)
            except OSError:pass
        # A fast helper may return before monitored()'s next poll. Don't erase
        # a pending control command by subsequently finalizing as 'done'.
        try:current = e.one('SELECT control FROM batches WHERE id=?', (b['id'],))
        except Exception:return
        if current['control'] or (b.get('owner') and not e.process_alive(b['owner'])):
            raise asyncio.CancelledError()
    finally:
        e.DB_TIMEOUT.reset(token)


async def _run(e, b, cfg):
    import corpus_files
    if not (corpus_files.base(e)/'pubmed/current.xml').is_file():
        return
    address = cfg.get('zoteroAddress', 'localhost:23119')
    candidates = e.rows("SELECT * FROM items WHERE batch=? AND state IN ('queued','running')", (b['id'],))
    candidates = [i for i in candidates if z.normalize_doi(json.loads(i['paper']).get('doi'))]
    if not candidates:
        return
    start = time.monotonic()
    stage_state, reason = 'skipped', ''
    with e.db() as db:
        run_id = db.execute("INSERT INTO stage_runs(batch,stage,started,state) VALUES(?,'zotero',?,'running')",
                            (b['id'], time.time())).lastrowid
    e.event(b, '', 'zotero', 'Zotero 本地补充开始', candidates=len(candidates), workers=2)
    results = {}
    service_down = False
    async def attempt(i, index):
        nonlocal service_down
        if service_down:return
        p = i['pmid']
        target = e.batch_dir(b)/'staging'/p/'zotero.pdf'
        target.parent.mkdir(parents=True, exist_ok=True)
        began = time.monotonic()
        e.execute("UPDATE items SET state='running',stage='zotero' WHERE batch=? AND pmid=?", (b['id'], p))
        result = {'outcome': 'interrupted', 'reason': 'Zotero 操作中断'}
        try:
            remaining = min(z.DOI_SECONDS, start + z.STAGE_SECONDS - time.monotonic())
            if remaining <= 0:
                raise TimeoutError()
            result = await helper({'mode': 'doi', 'root': str(e.ROOT), 'batch': b,
                                   'paper': json.loads(i['paper']), 'target': str(target), 'address': address,
                                   'deadline': time.monotonic() + remaining}, remaining)
            if result.get('unavailable'):service_down=True
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            result = {'outcome': 'skipped', 'reason': 'Zotero 本地补充达到时间上限'}
        except Exception as ex:
            result = {'outcome': 'skipped', 'reason': 'Zotero 本地补充异常：' + type(ex).__name__}
        finally:
            for temp in (target, target.with_suffix('.metadata.json')):
                try:temp.unlink(missing_ok=True)
                except OSError:result['cleanupError']='暂存文件清理失败'
            results[p] = (result, time.monotonic() - began)
    try:
        async with asyncio.timeout(max(.01, start + z.STAGE_SECONDS - min(1, z.STAGE_SECONDS / 10) - time.monotonic())):
            if not z.api_address(address):
                reason = 'Zotero 地址留空，跳过'
                return
            probe = await helper({'mode': 'probe', 'address': address}, z.PROBE_SECONDS)
            if probe.get('outcome') != 'available':
                reason = probe.get('reason', 'Zotero Local API 不可用')
                return
            await e.run_queue(list(enumerate(candidates)), 2, attempt)
            current = e.one('SELECT control FROM batches WHERE id=?', (b['id'],))
            if current['control'] or (b.get('owner') and not e.process_alive(b['owner'])):
                raise asyncio.CancelledError()
            stage_state = 'completed'
            if service_down:reason='Zotero Local API 中途不可用，停止剩余查询'
    except asyncio.CancelledError:
        stage_state = 'interrupted'
        reason = '用户暂停、取消或宿主退出'
        raise
    except TimeoutError:
        stage_state = 'timeout'
        reason = 'Zotero 探测或阶段时间预算耗尽'
    except Exception as ex:
        reason = 'Zotero 本地补充不可用：' + type(ex).__name__
    finally:
        records = []
        for i in candidates:
            result, elapsed = results.get(i['pmid'], ({'outcome': 'interrupted' if stage_state == 'interrupted' else 'skipped',
                                                      'reason': reason or 'Zotero 阶段未执行'}, 0))
            if stage_state == 'timeout' and result['outcome'] == 'interrupted':
                result = {'outcome': 'skipped', 'reason': reason}
            records.append((i['pmid'], result, elapsed))
        # A diagnostic failure must never replace an in-flight CancelledError.
        try:record_many(e, b, records)
        except Exception:pass
        duration = time.monotonic() - start
        try:e.execute('UPDATE stage_runs SET elapsed=?,state=? WHERE id=?', (duration, stage_state, run_id))
        except Exception:pass
        try:e.event(b, '', 'zotero', 'Zotero 本地补充结束', state=stage_state, reason=reason, wallSeconds=round(duration, 3))
        except OSError:pass


def record_many(e, b, records):
    # One bounded transaction, rather than a lock wait for every queued PMID.
    with e.db() as db:
        states = {r['pmid']: json.loads(r['data']) for r in db.execute(
            'SELECT pmid,data FROM item_progress WHERE batch=?', (b['id'],))}
        for p, result, elapsed in records:
            # Recover a durable receipt if the helper exited after publishing.
            item = db.execute('SELECT state,source FROM items WHERE batch=? AND pmid=?', (b['id'], p)).fetchone()
            if item and item['state'] == 'success' and item['source'] == 'Zotero':
                asset = db.execute('SELECT data FROM assets WHERE project=? AND pmid=?', (b['project'], p)).fetchone()
                if asset:result = {**json.loads(asset['data']), 'outcome': 'success'}
            state = states.get(p, {})
            state['zotero'] = {**state.get('zotero', {}), **result}
            db.execute('INSERT OR REPLACE INTO item_progress VALUES(?,?,?)',
                       (b['id'], p, json.dumps(state, ensure_ascii=False)))
            db.execute('INSERT INTO attempts(batch,pmid,stage,outcome,elapsed,detail) VALUES(?,?,?,?,?,?)',
                       (b['id'], p, 'zotero', result['outcome'], elapsed, json.dumps(result, ensure_ascii=False)))
            e.event(b, p, 'zotero', result.get('reason', 'Zotero PDF 补全成功'), **result)
