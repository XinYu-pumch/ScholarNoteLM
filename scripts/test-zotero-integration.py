"""Real Python RPC and independent download worker against an offline Local API.
No real Zotero data, external downloads, model API calls or application packaging.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'services/downloader'),str(ROOT/'services/downloader/tests')]
import engine as e
import corpus_files as files
import markdown_service as markdown
from zotero_fixture import Fixture
from test_downloads import pdf

fixture=Fixture()
try:
    with tempfile.TemporaryDirectory(prefix='zotero-rpc-',dir=ROOT/'tmp') as temp:
        e.ROOT,e.PROJECT=Path(temp),'integration'
        for name in ('services','runtimes','models'):(e.ROOT/name).symlink_to(ROOT/name,target_is_directory=True)
        e.write_json(e.ROOT/'config/storage.json',{'workspace':str(e.ROOT/'workspace'),'projects':{'integration':'MappedProject'}})
        env={**os.environ,'SCHOLARNOTELM_ROOT':temp,'HTTP_PROXY':'http://127.0.0.1:1','HTTPS_PROXY':'http://127.0.0.1:1','ALL_PROXY':'http://127.0.0.1:1'}
        base=files.base(e)
        e.atomic(base/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><ArticleTitle>Offline fixture {p}</ArticleTitle><Abstract><AbstractText>Fixture abstract.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/test</ArticleId></ArticleIdList></PubmedData></PubmedArticle>' for p in ['1','2'])+'</PubmedArticleSet>')
        source=e.ROOT/'本机 PDF%20.pdf';source.write_bytes(pdf());fixture.paths['ATTACH01']=source
        original=hashlib.sha256(source.read_bytes()).hexdigest()
        def rpc(action,**args):
            proc=subprocess.run([sys.executable,str(ROOT/'services/downloader/engine.py')],
                input=json.dumps({'action':action,'args':{'project':'integration',**args}}),text=True,capture_output=True,env=env,timeout=10)
            result=json.loads(proc.stdout);assert result['ok'],result
            return result['data']
        def wait(bid):
            start=time.monotonic()
            while time.monotonic()-start<10:
                b=e.one('SELECT * FROM batches WHERE id=?',(bid,))
                if b['state'] in ('done','paused','cancelled'):break
                time.sleep(.05)
            assert b['state']=='done',b
            # Independent worker remains briefly idle after completion. Wait for its lock to release.
            while time.monotonic()-start<12:
                lock=e.worker_lock()
                if lock:lock.close();break
                time.sleep(.05)
            assert lock,'worker did not release lock'
            return b,time.monotonic()-start
        rpc('settings.save',fastOa=False,mirrors=[],zoteroAddress=fixture.address)
        fixture.mode='slow';start=time.monotonic()
        bid=rpc('start',papers=[{'pmid':'1','doi':'10.1234/test','title':'Fixture'}])['id']
        b,elapsed=wait(bid)
        assert len(fixture.calls)==1,fixture.calls
        assert elapsed<8,elapsed
        assert e.one('SELECT state FROM items WHERE batch=?',(bid,))['state']=='failed'
        assert (base/'literature_without_pdf.txt').read_text()=='1\n2\n'
        print('Independent worker: continuous-response probe timed out, batch finalized',flush=True)
        fixture.mode='';fixture.calls.clear()
        bid=rpc('start',papers=[{'pmid':'1','doi':'10.1234/test','title':'Fixture'}])['id']
        b,elapsed=wait(bid)
        assert e.one('SELECT state,source FROM items WHERE batch=?',(bid,))=={'state':'success','source':'Zotero'}
        info=json.loads(e.one('SELECT data FROM assets WHERE pmid=?',('1',))['data'])
        assert info['attachmentKey']=='ATTACH01' and info['sha256']==original
        report=json.loads((e.batch_dir(b)/'download_report.json').read_text())
        assert report['counts']=={'success':1} and report['stages'][-1]['success']==1
        assert report['stageRuns'][-1]['stage']=='zotero'
        assert (base/'literature_without_pdf.txt').read_text()=='2\n'
        assert '1\tpdf/1.pdf\tZotero' in (base/'literature_pdf_sources.txt').read_text()
        assert (e.batch_dir(b)/'literature_without_pdf.txt').read_text()==''
        assert not list((e.batch_dir(b)/'staging').rglob('*.pdf'))
        assert not list(base.glob('metadata/markdown-job*')),'standalone download must not auto-convert'
        assert 'PRIVATE' not in (e.batch_dir(b)/'download_report.txt').read_text()
        assert hashlib.sha256(source.read_bytes()).hexdigest()==original
        # Verify the existing opt-in handoff receives the newly registered Zotero PDF,
        # without invoking Marker or any model in this test.
        cfg=json.loads(b['config']);cfg.update(convertAfter=True,markdownRequestId=bid)
        handoff={**b,'config':json.dumps(cfg)}
        with patch.object(markdown,'rpc',return_value={'id':'fixture-conversion'}) as start_conversion:
            result=e.finish_markdown(handoff)
            assert result['state']=='started',result
            assert start_conversion.call_args.args[1]=='start'
        result={"success":True,"checks":["real RPC and independent download worker", "hard slow-response timeout", "strict Zotero success", "environment proxies bypassed", "mapped project path", "reports and both missing lists", "no temporary files", "standalone download stays standalone", "existing conversion handoff", "source fixture unchanged"]}
        (ROOT/'tmp/zotero-integration-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False),flush=True)
finally:
    fixture.close()
