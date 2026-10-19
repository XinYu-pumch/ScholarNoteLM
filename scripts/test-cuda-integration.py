"""Real local-model conversion in a disposable root; never opens user projects."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import test_paths

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'services/downloader')]
import engine as e
import corpus_files
import markdown_service
sys.path.insert(0, str(ROOT/'services/marker'))
from inference_client import InferenceClient
from unittest.mock import patch
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def fixture(path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    lines = ['Local accelerator validation', 'Methods',
             'This synthetic document contains no patient data or private research.',
             'We compare local CPU and GPU conversion using the same model files.',
             'Results', 'The pipeline should preserve readable text and publish Markdown.',
             'A second conversion should reuse the existing output without inference.']
    stream = DecodedStreamObject()
    commands = ['BT /F1 12 Tf 54 720 Td']
    for line in lines:
        commands.extend(['('+line+') Tj', '0 -28 Td'])
    commands.append('ET'); stream.set_data('\n'.join(commands).encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    for _ in range(7):writer.add_page(page)
    with path.open('wb') as out:writer.write(out)


def main():
    with tempfile.TemporaryDirectory(prefix='cuda-integration-', dir=ROOT/'tmp') as temp:
        root = Path(temp)
        e.ROOT, e.PROJECT = root, 'test'
        (root/'tmp').mkdir()
        for name in ('services','runtimes','models'):
            test_paths.link_directory(root/name, ROOT/name)
        base = corpus_files.base(e)
        e.atomic(base/'pubmed/current.xml', '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>CUDA fixture</ArticleTitle><Abstract><AbstractText>Synthetic evidence only.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
        (base/'pdf').mkdir(exist_ok=True)
        fixture(base/'pdf/1.pdf')
        corpus_files.reconcile(e)
        env = {**os.environ, 'SCHOLARNOTELM_ROOT':str(root), 'PYTHONUTF8':'1',
               'HTTP_PROXY':'http://127.0.0.1:9', 'HTTPS_PROXY':'http://127.0.0.1:9'}
        results = []
        for device in ('auto', 'cpu'):
            report = base/'logs'/('cuda-test-'+device); report.mkdir(parents=True)
            job = {'id':'cuda'+device, 'state':'queued', 'mode':'convert', 'pmids':['1'],
                   'config':{**markdown_service.DEFAULTS,'device':device}, 'logPath':str(report),
                   'completed':0,'failed':0,'skipped':0,'items':[], 'force':True, 'replaceEdited':False}
            e.write_json(markdown_service.job_path(e), job)
            start = time.monotonic()
            with (report/'worker.log').open('w',encoding='utf-8') as log:
                process = subprocess.run([str(test_paths.python(ROOT,'marker')), str(ROOT/'services/marker/worker.py'),
                              '--project','test','--job',job['id']],env=env,cwd=root,stdout=log,stderr=log,timeout=900)
            result = json.loads(markdown_service.job_path(e).read_text(encoding='utf-8'))
            if process.returncode or result.get('failed') or result.get('completed') != 1:
                print((report/'worker.log').read_text(encoding='utf-8')[-14000:])
                raise AssertionError(result)
            expected = 'cuda' if device=='auto' else 'cpu'
            assert result['device']==expected, result
            content = (base/'markdown/1.md').read_text(encoding='utf-8')
            assert 'synthetic document' in content.lower(), content
            results.append({'requested':device,'actual':result['device'],'seconds':round(time.monotonic()-start,2),
                            'characters':len(content),'fallbacks':result.get('acceleratorFallbacks',[])})
            print(json.dumps(results[-1]),flush=True)
        # Inject only the GPU failure response, then use the real fresh CPU subprocess
        # and real models. This exercises recovery without exhausting the user's GPU.
        import compute_devices
        client=InferenceClient(root, compute_devices.detect(root))
        request=client.request
        first=True
        def fail_gpu_once(*args):
            nonlocal first
            if first:
                first=False
                return {'ok':False,'kind':'accelerator','error':'CUDA error: injected integration failure'}
            return request(*args)
        stage=root/'tmp/fallback';stage.mkdir()
        try:
            with patch.object(client,'request',side_effect=fail_gpu_once):
                out=client.convert(base/'pdf/1.pdf',stage,1,lambda:False)
            assert client.selection['device']=='cpu' and len(client.fallbacks)==1
            assert 'synthetic document' in (out/'1.md').read_text(encoding='utf-8').lower()
            print('Injected GPU failure -> real CPU subprocess conversion passed',flush=True)
        finally:client.close()
        (ROOT/'tmp/cuda-integration-result.json').write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__ == '__main__':main()
