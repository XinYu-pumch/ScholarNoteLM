"""Offline Rust import and Python downstream replay; source XML files remain read-only."""
import json,os,subprocess,tempfile,sys,xml.etree.ElementTree as ET
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root/'services/downloader'))
import engine as e,storage,vector_chunks,review_service,corpus_files
sources=[Path(p).resolve() for p in sys.argv[1:]] or [root/'services/downloader/tests/fixtures/pubmed-book.xml']
with tempfile.TemporaryDirectory(prefix='hus-xml-replay-',dir=root/'tmp') as d:
 app=Path(d);(app/'tmp').mkdir();(app/'services').symlink_to(root/'services');(app/'runtimes').mkdir();(app/'runtimes/downloader').symlink_to(root/'runtimes/downloader')
 e.ROOT=app
 for i,source in enumerate(sources):
  project='Replay'+str(i);raw=source.read_text();doc=ET.fromstring(raw)
  expected={r.findtext('MedlineCitation/PMID') or r.findtext('BookDocument/PMID') for r in doc};expected.discard(None)
  proc=subprocess.run([str(root/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':'xml.import','args':{'project':project,'name':'offline original batch','xml':raw}}),text=True,capture_output=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(app)},timeout=40)
  response=json.loads(proc.stdout);assert response['ok'],response
  imported=response['data']['corpus'];assert imported['included']==len(expected),(imported['included'],len(expected))
  e.PROJECT=project;assert corpus_files.current(e)==expected
  papers,_=vector_chunks.xml_articles(e);assert set(papers)==expected
  _,_,abstracts=review_service.abstracts(e);assert abstracts['total']==len(expected)
  chapters=[p for p,a in papers.items() if a.get('recordType')=='book_chapter']
  print(json.dumps({'batch':str(source),'xmlRecords':len(expected),'imported':imported['included'],'vectorRecords':len(papers),'reviewRecords':abstracts['total'],'chapters':chapters},ensure_ascii=False),flush=True)
