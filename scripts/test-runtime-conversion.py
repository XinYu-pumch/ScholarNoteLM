"""Real offline Marker smoke test with a synthetic PDF and disposable project."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import test_paths
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Newly provisioned source checkout')
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0,str(root/'services/downloader'))
    from engine import process_alive
    with tempfile.TemporaryDirectory(prefix='runtime-conversion-', dir=root / 'tmp') as temporary:
        fixture = Path(temporary)
        for name in ['services', 'runtimes', 'models']:
            test_paths.link_directory(fixture/name,root/name)
        env = {**os.environ, 'SCHOLARNOTELM_ROOT': str(fixture), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8':'1'}
        python = test_paths.python(root)
        # This fixture has no copied settings or bibliography and no external URLs.
        prepare = r'''
import os,sys
from pathlib import Path
root=Path(os.environ['SCHOLARNOTELM_ROOT']);sys.path.insert(0,str(root/'services/downloader'))
import engine as e,storage
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
storage.initialize(root)
storage.register(root,{'project':'test','folder':'Test','data':{'id':'test'}})
base=root/'workspace/Test';(base/'pubmed/current.xml').write_text('<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>999000001</PMID><Article><ArticleTitle>Installation verification</ArticleTitle><Abstract><AbstractText>Synthetic installation fixture.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
stream=DecodedStreamObject();stream.set_data(b'BT /F1 16 Tf 50 730 Td (Installation verification) Tj /F1 11 Tf 0 -35 Td (This synthetic research document checks offline PDF conversion.) Tj 0 -22 Td (The local model preserves readable text without a remote language model.) Tj 0 -22 Td (No patient records, personal projects or API credentials are included.) Tj ET')
page[NameObject('/Contents')]=writer._add_object(stream)
writer.write(base/'pdf/999000001.pdf')
'''
        subprocess.run([str(python), '-c', prepare], env=env, check=True)

        def rpc(action, **kwargs):
            response = subprocess.run([str(python), str(root / 'services/downloader/engine.py')],
                                      input=json.dumps({'action': action, 'args': {'project': 'test', **kwargs}}),
                                      text=True, encoding='utf-8', capture_output=True, env=env, timeout=30)
            value = json.loads(response.stdout)
            if not value.get('ok'):
                raise AssertionError(value)
            return value['data']

        assert rpc('markdown.settings')['ready']
        rpc('markdown.start', indexAfter=False)
        deadline = time.monotonic() + 600
        job = None
        try:
            while time.monotonic() < deadline:
                job = rpc('markdown.status')['job']
                if job and job['state'] not in ('queued', 'running', 'stopping'):
                    break
                time.sleep(1)
            assert job and job['state'] == 'done' and job['completed'] == 1 and job['failed'] == 0, job
            text = (fixture / 'workspace/Test/markdown/999000001.md').read_text()
            assert 'Installation verification' in text and 'synthetic' in text and 'credentials' in text, text
            print('Real offline Marker conversion passed: synthetic PDF -> raw and cleaned Markdown.')
        finally:
            # A failed/slow worker must not outlive a test that removes its project.
            if job and job.get('pid') and job['state'] in ('queued', 'running', 'stopping'):
                import signal
                try:
                    os.kill(job['pid'], signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if job and job.get('pid'):
                end=time.monotonic()+30
                while process_alive(job['pid']) and time.monotonic()<end:
                    time.sleep(.1)
                if process_alive(job['pid']):
                    raise AssertionError('Conversion worker did not exit after publishing its result')


if __name__ == '__main__':
    main()
