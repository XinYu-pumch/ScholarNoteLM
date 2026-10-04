"""Re-fetch the previous 20-article sample through the actual app engine, isolated."""
import asyncio, hashlib, json, sys, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/downloader'))
import engine as e
e.load_sources()
exp=ROOT/'experiments/scihub-20260920'
papers=json.loads((exp/'papers.json').read_text())
prior=json.loads((exp/'optimized-two-files/result.json').read_text())['articles']
fixture=ROOT/'tmp'/('source-cache-live-'+str(time.time_ns()));fixture.mkdir()
e.ROOT=fixture;e.PROJECT='Sample'
e.save_settings({'mirrors':['https://sci-hub.ru','https://sci-hub.su']})
for row in prior:
 if not row.get('success'):continue
 body=(exp/'optimized-two-files'/f"{row['pmid']}.pdf").read_bytes()
 assert hashlib.sha256(body).hexdigest()==row['sha256'] and row['doiMatched']
 e.remember_sources(row,{'source':'Sci-Net' if 'sci-net.xyz' in row['url'] else 'Sci-Hub','fileUrl':row['url'],'sha256':row['sha256']})
with patch.object(e,'launch'):batch=e.create({'project':'Sample','papers':papers})
b=e.one('SELECT * FROM batches WHERE id=?',(batch['id'],))
hits={p['doi'] for p in papers if p['bloom']}
bloom=SimpleNamespace(contains=lambda doi:doi in hits,close=lambda:None)
async def unavailable(*args):return None,'Isolated Sci source verification'
start=time.monotonic()
with patch.object(e,'bloom_info',return_value={}),patch.object(e.badr,'SciHubBloomFilter',return_value=bloom),patch.object(e,'source_s3',unavailable),patch.object(e,'source_unpaywall',unavailable):
 asyncio.run(e.run_batch(b))
report=json.loads((e.batch_dir(b)/'download_report.json').read_text())
result={'fixture':str(fixture),'report':str(e.batch_dir(b)/'download_report.json'),'wallSeconds':round(time.monotonic()-start,3),'counts':report['counts'],'sourceCacheSuccess':report['sourceCacheSuccess'],'scihubSuccessByBloom':report['scihubSuccessByBloom'],'sources':{},'verified':[]}
from pypdf import PdfReader
import re
for asset in e.rows('SELECT data FROM assets'):
 info=json.loads(asset['data']);p=next(p for p in papers if p['pmid']==info['pmid'])
 path=e.asset_path('Sample',info);body=path.read_bytes()
 assert hashlib.sha256(body).hexdigest()==info['sha256']
 text=''.join(page.extract_text() or '' for page in PdfReader(path).pages)
 assert p['doi'].lower() in re.sub(r'\s+','',text).lower()
 result['verified'].append(p['pmid']);result['sources'][info['source']]=result['sources'].get(info['source'],0)+1
(ROOT/'docs/SOURCE_CACHE_LIVE_TEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
