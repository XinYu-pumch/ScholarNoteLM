"""Disposable process for Zotero metadata, file copying, parsing and publication.

Only the supervisor launches this helper. It never writes to Zotero. There are
no child processes/threads for PDF parsing; killing this process stops that work.
"""
import asyncio
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
import pubmed_xml
from urllib.parse import urlsplit
import artifact_state
import corpus_files
import engine as e
import zotero_local as z


def current_doi(p):
    path = corpus_files.base(e)/'pubmed/current.xml'
    root = ET.fromstring(path.read_bytes())
    if root.tag != 'PubmedArticleSet':
        return None
    for node,citation,article,data in pubmed_xml.records(root):
        if citation.findtext('PMID') == p:
            for aid in pubmed_xml.doi_elements(node,citation,article,data):
                if (aid.get('IdType') or aid.get('EIdType') or '').lower() == 'doi':
                    return z.normalize_doi(aid.text)
            return ''
    return None


def control_check(b, deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('Zotero 时间预算已耗尽')
    row = e.one('SELECT state,control FROM batches WHERE id=?', (b['id'],))
    if row['state'] != 'running' or row['control'] or (b.get('owner') and not e.process_alive(b['owner'])):
        raise ValueError('批次已停止')


async def run(request):
    if request['mode'] == 'probe':
        async with z.LocalAPI(request['address']) as api:
            await api.probe()
        return {'outcome': 'available'}
    e.DB_TIMEOUT.set(.2)
    e.ROOT = Path(request['root'])
    e.PROJECT = request['batch']['project']
    b, paper = request['batch'], request['paper']
    p = e.pmid(paper['pmid'])
    target = Path(request['target'])
    deadline = request['deadline']
    doi = current_doi(p)
    if not doi:
        return {'outcome': 'skipped', 'reason': '当前 PubMed 文献没有 DOI 或已移出集合'}
    control_check(b, deadline)
    epoch = artifact_state.epoch(e, p)
    dest = corpus_files.folder(e, 'pdf')/f'{p}.pdf'
    original = z.fingerprint(dest)
    if original:
        try:
            checked = e.validate_pdf(dest)
        except (ValueError, OSError):
            pass
        else:
            if original != z.fingerprint(dest):
                return {'outcome': 'skipped', 'reason': '项目 PDF 正在变化'}
            # A manually supplied valid PDF appeared during network stages.
            with corpus_files.lock(e):
                control_check(b, deadline)
                if current_doi(p) != doi or artifact_state.epoch(e, p) != epoch or original != z.fingerprint(dest):
                    raise ValueError('项目文献或 PDF 已改变')
                info = {**checked, 'source': '用户提供的 PDF', 'pmid': p, 'path': f'pdf/{p}.pdf', 'archived': False}
                e.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)', (e.PROJECT, p, json.dumps(info)))
                z.cache_fingerprint(e, dest, checked['sha256'])
                e.execute("UPDATE items SET state='skipped',source='已有本地 PDF',bytes=? WHERE batch=? AND pmid=?",
                          (checked['bytes'], b['id'], p))
            return {'outcome': 'skipped', 'reason': '已有有效项目 PDF'}
    async with z.LocalAPI(request['address']) as api:
        candidates = await api.candidates(doi)
    state = e.progress(b['id'], p)
    previous = state.get('zotero', {}).get('attachmentKey')
    rejected = []
    for candidate in z.rank(candidates, previous):
        control_check(b, deadline)
        target.unlink(missing_ok=True)
        try:
            checked, signature = z.copy_checked(candidate, target, e.validate_pdf)
        except Exception as ex:
            # PDF parsers can raise errors outside their own documented hierarchy.
            rejected.append({'attachmentKey': candidate['key'], 'error': type(ex).__name__})
            target.unlink(missing_ok=True)
            continue
        rule, data = candidate['rule'], candidate['data']
        info = {'source': 'Zotero', 'doi': doi, 'parentKey': candidate['parent'],
                'attachmentKey': candidate['key'], 'attachmentTitle': data['title'],
                'ruleId': rule['id'], 'ruleVersion': z.RULES['version'],
                'priority': rule['priority'], 'manuscriptKind': rule['kind'],
                'sourceDomain': urlsplit(data['url']).hostname, 'rejectedCandidates': rejected}
        # Original URL is intentionally omitted; signed query strings never reach logs/cache/UI.
        def guard():
            corpus_files.folder(e, 'pdf')
            control_check(b, deadline)
            membership = artifact_state.membership(e)
            if current_doi(p) != doi or artifact_state.epoch(e, p) != epoch or p in membership.get('pending', []):
                raise ValueError('文献已移出、DOI 或生命周期已改变')
            if (corpus_files.base(e)/'metadata/pdf-cleared.json').exists():
                raise ValueError('PDF 已被清空')
            if z.fingerprint(dest) != original:
                raise ValueError('项目 PDF 已出现或改变，不覆盖')
            if z.fingerprint(target) != signature:
                raise ValueError('校验后的暂存文件已改变')
            control_check(b, deadline)
        try:
            await e.publish(b, paper, target, info, checked=checked, guard=guard)
        except (ValueError, TimeoutError):
            raise
        except OSError as ex:
            rejected.append({'attachmentKey': candidate['key'], 'error': type(ex).__name__})
            # Only retry another candidate if publication did not consume staging.
            if not target.exists():
                raise
            continue
        state = e.progress(b['id'], p)
        state['zotero'] = {**info, **checked, 'outcome': 'success'}
        e.save_progress(b['id'], p, state)
        return {'outcome': 'success', **info, **checked}
    return {'outcome': 'skipped', 'reason': '无符合严格白名单且可读的本机 PDF', 'rejectedCandidates': rejected}


if __name__ == '__main__':
    try:
        result = asyncio.run(run(json.loads(sys.stdin.read())))
    except Exception as ex:
        # Don't serialize exception messages containing source URLs or local paths.
        import httpx
        unavailable = isinstance(ex, (z.Unavailable, httpx.TransportError, TimeoutError))
        result = {'outcome': 'skipped', 'reason': str(ex) if isinstance(ex, z.Unavailable) else 'Zotero 补充未完成：' + type(ex).__name__,
                  'unavailable': unavailable}
    print(json.dumps(result, ensure_ascii=False), flush=True)
