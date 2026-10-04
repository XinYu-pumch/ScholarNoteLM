"""Exercise real Rust XML mutations and the offline re-clean worker on isolated data."""
import hashlib,io,json,os,shutil,subprocess,tempfile,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from pypdf import PdfWriter
ROOT=Path(__file__).resolve().parents[1]
TEST=Path(tempfile.mkdtemp(prefix='markdown-integration-',dir=ROOT/'tmp'))
for name in ['services','runtimes','models']:(TEST/name).symlink_to(ROOT/name,target_is_directory=True)
ENV={**os.environ,'SCHOLARNOTELM_ROOT':str(TEST),'PYTHONDONTWRITEBYTECODE':'1'}
BIN=ROOT/'cache/tauri-target/debug/research-cli'
def rpc(action,**args):
 r=subprocess.run([str(BIN)],input=json.dumps({'action':action,'args':args}),text=True,capture_output=True,env=ENV,check=True)
 v=json.loads(r.stdout)
 if not v['ok']:raise RuntimeError(v['error'])
 return v['data']
def xml(ids):return '<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{i}</PMID><Article><ArticleTitle>Paper {i}</ArticleTitle></Article></MedlineCitation></PubmedArticle>' for i in ids)+'</PubmedArticleSet>'
rpc('storage.initialize')
a=rpc('xml.import',project='test',name='A',xml=xml([101,102]));aid=a['queries'][0]['id']
b=rpc('xml.import',project='test',name='B',xml=xml([102,103]));bid=next(q['id'] for q in b['queries'] if q['id']!=aid)
base=TEST/'workspace/test';pdf=PdfWriter();pdf.add_blank_page(width=100,height=100);buf=io.BytesIO();pdf.write(buf)
for p in ['101','102','103']:(base/'pdf'/f'{p}.pdf').write_bytes(buf.getvalue())
raw='# Original heading\n\n'+('Retained long paragraph. '*8)+'\n\nREMOVE publisher line\n\nshort\n'
(base/'markdown/raw').mkdir(exist_ok=True);(base/'markdown/raw/101.md').write_text(raw);(base/'markdown/101.md').write_text('old clean output')
(base/'metadata/markdown').mkdir(exist_ok=True);(base/'metadata/markdown/101.json').write_text(json.dumps({'pdfSha256':hashlib.sha256(buf.getvalue()).hexdigest()}))
after=rpc('query.archive',project='test',id=aid,value=True)
assert after['corpus']['included']==2 and (base/'pdf/redundant/101.pdf').exists() and not (base/'pdf/101.pdf').exists()
assert (base/'pdf/102.pdf').exists() and not (base/'markdown/redundant/raw/101.md').exists() and not (base/'markdown/raw/101.md').exists()
rpc('query.archive',project='test',id=aid,value=False)
assert (base/'pdf/101.pdf').read_bytes()==buf.getvalue() and not (base/'markdown/raw/101.md').exists()
# Emulate newly generated raw output to independently exercise the re-clean worker.
(base/'markdown/raw/101.md').write_text(raw)
membership=json.loads((base/'metadata/corpus-membership.json').read_text())
(base/'metadata/markdown/101.json').write_text(json.dumps({'pdfSha256':hashlib.sha256(buf.getvalue()).hexdigest(),'rebuildEpoch':membership['epochs']['101']}))
# Concurrent status reads reproduce the UI's two polling panels without lock errors.
with ThreadPoolExecutor(max_workers=4) as pool:
 states=list(pool.map(lambda _:rpc('markdown.status',project='test'),range(12)))
assert all(s['pdfCount']==3 for s in states)
rpc('markdown.settings.save',badrCleanup=True,removeLines=['REMOVE publisher'])
job=rpc('markdown.start',project='test',mode='clean',pmids=['101'])
for _ in range(40):
 state=rpc('markdown.status',project='test')
 if state['job']['state'] not in ('queued','running','stopping'):break
 time.sleep(.15)
assert state['job']['state']=='done' and state['job']['completed']==1,state['job']
assert (base/'markdown/raw/101.md').read_text()==raw
clean=(base/'markdown/101.md').read_text();assert 'REMOVE publisher' not in clean and 'short' not in clean and 'Retained long paragraph.' in clean
assert (Path(state['job']['logPath'])/'marker.log').read_text()=='' # no model loading for re-clean
rpc('query.archive',project='test',id=bid,value=True)
assert (base/'pdf/redundant/103.pdf').exists()
result=rpc('download.clear',project='test',confirm='test');assert result['pdf']==3
rpc('markdown.reconcile',project='test');assert not list((base/'pdf').rglob('*.pdf'))
result={'passed':True,'fixture':str(TEST),'checks':['XML union / overlapping query provenance','real XML mutation archives/restores only PDF and deletes derived Markdown','12 concurrent status requests','offline re-clean subprocess preserving raw, no models loaded','clear includes redundant PDFs and does not restore them']}
(ROOT/'docs/MARKDOWN_CORPUS_TEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
