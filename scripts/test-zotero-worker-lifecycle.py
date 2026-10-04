"""Exercise real CLI worker ownership in disposable projects without network requests."""
import json, os, subprocess, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'cache/tauri-target/debug/research-cli'

with tempfile.TemporaryDirectory(prefix='zotero-lifecycle-', dir=ROOT/'tmp') as tmp:
    app = Path(tmp)
    (app/'runtimes').mkdir()
    (app/'services').symlink_to(ROOT/'services', target_is_directory=True)
    (app/'runtimes/downloader').symlink_to(ROOT/'runtimes/downloader', target_is_directory=True)
    env = {**os.environ, 'SCHOLARNOTELM_ROOT': tmp, 'PYTHONDONTWRITEBYTECODE': '1'}

    def rpc(action, wait=False, **args):
        result = subprocess.run([str(CLI), *(['--wait'] if wait else [])],
            input=json.dumps({'action': action, 'args': args}), text=True,
            capture_output=True, env=env, timeout=45, check=True)
        response = json.loads(result.stdout)
        assert response['ok'], response
        return response['data']

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf8')

    def preview(project):
        rpc('workspace', project=project)
        collection = {'key': 'COLLECT1', 'name': 'Fixture', 'path': 'Fixture'}
        write(app/f'workspace/{project}/metadata/zotero-previews/fixture.json', {
            'collection': collection, 'selectedCollections': [collection],
            'items': [{'key': 'MISSING1', 'doi': ''}], 'total': 1,
            'address': 'localhost:1'})  # Missing DOI skips PubMed and PDF network calls.

    for project, wait in [('foreground', True), ('background', False)]:
        preview(project)
        started = rpc('zotero.start', wait=wait, project=project, preview='fixture')
        assert started['process']['pid'] > 0 and started['process']['jobId'] == started['id']
        if wait:
            assert started['state'] == 'completed', started
        until = time.monotonic() + 40
        while True:
            job = rpc('zotero.status', project=project)
            if job['state'] not in ('queued', 'running') and not job['process']['lockHeld']:
                break
            assert time.monotonic() < until, job
            time.sleep(.1)
        assert job['state'] == 'completed', job
        assert job['process']['mode'] == 'worker' and job['process']['jobId'] == job['id']
        assert job['processed'] == 1 and job['rows'][0]['status'] == 'missing_doi'
        workspace = rpc('workspace', project=project)
        assert len(workspace['queries']) == 1 and workspace['queries'][0]['xmlExists']
        before = job['runId']
        # Re-entering a completed worker must not publish a second source or run.
        subprocess.run([str(CLI), '--zotero-worker', project, job['id']],
            env=env, capture_output=True, text=True, timeout=10, check=True)
        assert rpc('zotero.status', project=project)['runId'] == before
        assert len(rpc('workspace', project=project)['queries']) == 1

    # Restore a pre-publication interrupted job using the same worker and source ID.
    project = 'retry'
    preview(project)
    base = app/f'workspace/{project}/metadata'
    snapshot = json.loads((base/'zotero-previews/fixture.json').read_text())
    write(base/'zotero-imports/retryjob/snapshot.json', snapshot)
    write(base/'zotero-job.json', {'id': 'retryjob', 'state': 'interrupted',
        'created': 1, 'started': 2, 'finished': 3, 'error': 'old interruption',
        'collection': snapshot['collection'], 'total': 1})
    subprocess.run([str(CLI), '--zotero-worker', project, 'retryjob'],
        env=env, capture_output=True, text=True, timeout=45, check=True)
    job = rpc('zotero.status', project=project)
    assert job['state'] == 'completed' and not job['error'], job
    assert job['attempts'][0]['error'] == 'old interruption'
    assert len(rpc('workspace', project=project)['queries']) == 1

print('PASS: foreground wait, detached worker receipt, no duplicate publication, retry error history')
