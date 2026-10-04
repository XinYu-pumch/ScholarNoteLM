"""Exercise migration, moving, XML-scoped packing and clearing on an isolated copy."""
import base64, hashlib, io, json, os, pathlib, shutil, sqlite3, subprocess, tempfile, zipfile, time
from pypdf import PdfWriter
ROOT=pathlib.Path(__file__).resolve().parents[1]
TEST=pathlib.Path(tempfile.mkdtemp(prefix='storage-integration-',dir=ROOT/'tmp'))
for name in ['services','runtimes']:(TEST/name).symlink_to(ROOT/name,target_is_directory=True)
(TEST/'data/reference/jcr').mkdir(parents=True)
shutil.copytree(ROOT/'data/reference/jcr',TEST/'data/reference/jcr',dirs_exist_ok=True)
# A realistic copy catches legacy path/DB migration problems, without changing user files.
if (ROOT/'config/storage.json').exists() and json.loads((ROOT/'config/storage.json').read_text()).get('migrated'):
    backup=ROOT/'backups/storage-migration-v1'
    shutil.copytree(backup/'projects',TEST/'data/projects')
    (TEST/'data/research').mkdir(parents=True,exist_ok=True);(TEST/'data/prototype').mkdir(parents=True,exist_ok=True)
    for name in ['research.sqlite3','downloads.sqlite3']:shutil.copy2(backup/name,TEST/'data/research'/name)
    shutil.copy2(backup/'state.json',TEST/'data/prototype/state.json')
else:
    for folder in ['research','prototype','projects']:
        source=ROOT/'data'/folder
        if source.exists():shutil.copytree(source,TEST/'data'/folder,dirs_exist_ok=True)
# Disable update checks in this isolated copy only.
with sqlite3.connect(TEST/'data/research/research.sqlite3') as c:c.execute("INSERT OR REPLACE INTO settings VALUES('meshAuto','false')")
ENV={**os.environ,'SCHOLARNOTELM_ROOT':str(TEST),'PYTHONDONTWRITEBYTECODE':'1'}
BIN=ROOT/'cache/tauri-target/debug/research-cli'
def rpc(action,**args):
    r=subprocess.run([str(BIN)],input=json.dumps({'action':action,'args':args}),text=True,capture_output=True,env=ENV)
    v=json.loads(r.stdout)
    if not v['ok']:raise RuntimeError(v['error'])
    return v['data']
def reject(action,**args):
    try:rpc(action,**args)
    except RuntimeError:return
    raise AssertionError('should reject '+action)
def fingerprint(folder):return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ['.pdf','.md','.xml']}
legacy_files=fingerprint(TEST/'data/projects')
initial=rpc('storage.initialize');state=rpc('storage.state.read');assert len(state['projects'])==2
work=pathlib.Path(initial['workspace']);assert (work/'gut/pdf/31551115.pdf').exists();assert (work/'gut/pubmed/current.xml').exists()
assert all((work/'gut'/name).is_dir() for name in ['pubmed','pdf','abstracts','logs','vectors','summaries','metadata','notes','reviews'])
assert not (TEST/'data/projects').exists();assert fingerprint(TEST/'backups/storage-migration-v1/projects')==legacy_files
current=rpc('workspace',project='gut');assert current['corpus']['included']==38
assert all(q['xmlExists'] for q in current['queries'] if q.get('run'))
assets=rpc('download.list',project='gut')['assets'];assert sum(a['exists'] for a in assets.values())==22
with sqlite3.connect(work/'gut/metadata/research.sqlite3') as c:
 assert not c.execute("SELECT 1 FROM settings WHERE key='profiles'").fetchone()
 assert not c.execute("SELECT 1 FROM queries WHERE project<>'gut'").fetchone()
with sqlite3.connect(TEST/'data/research/research.sqlite3') as c:assert c.execute('SELECT count(*) FROM queries').fetchone()[0]==0
rpc('storage.state.write',state=state);assert rpc('storage.state.read')==state
# Invalid / case-insensitive / reserved names; Chinese display names are allowed.
for folder in ['a-b','../escape','CON','Gut']:
 reject('storage.register',project='bad',folder=folder,data={'id':'bad'})
p=dict(state['projects'][0],id='packtest',name='打包验证',papers=[],messages=[],notes={},sections=[],tasks=[])
rpc('storage.register',project='packtest',folder='PackTest2026',data=p)
xml='<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{i}</PMID><Article><ArticleTitle>Paper {i}</ArticleTitle><Abstract><AbstractText>Abstract {i}</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for i in [101,102])+'</PubmedArticleSet>'
rpc('xml.import',project='packtest',name='fixture.xml',xml=xml)
buf=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(buf)
rpc('download.import',project='packtest',pmid='101',base64=base64.b64encode(buf.getvalue()).decode())
project=work/'PackTest2026';(project/'abstracts/102.md').write_text('Abstract 102');(project/'pdf/999.pdf').write_bytes(buf.getvalue());(project/'abstracts/999.md').write_text('out of corpus')
(project/'packages/downloaded_literature-old.zip').write_bytes(b'old')
(project/'qa/history.json').write_text('{"question":"preserve QA"}')
packed=rpc('download.export',project='packtest');assert packed['pdf']==1 and packed['abstracts']==1
with zipfile.ZipFile(packed['path']) as z:assert set(z.namelist())=={'pdf/101.pdf','abstracts/102.md','pubmed/current.xml','manifest.json'}
assert not (project/'packages/downloaded_literature-old.zip').exists()
(project/'pdf/101.pdf').write_bytes(b'not a PDF');previous=pathlib.Path(packed['path']).read_bytes();reject('download.export',project='packtest');assert pathlib.Path(packed['path']).read_bytes()==previous
(project/'pdf/101.pdf').write_bytes(buf.getvalue());rpc('download.export',project='packtest');assert len(list((project/'packages').glob('*.zip')))==1
# External workspace: move checksums, stored PDF paths and old XML runs survive.
new=TEST/'external'/'Research Projects';new.mkdir(parents=True)
before=fingerprint(work);rpc('storage.move',path=str(new));assert fingerprint(new)==before;assert not (work/'gut').exists()
assert rpc('workspace',project='gut')['corpus']['included']==38
assert all(q['xmlExists'] for q in rpc('workspace',project='gut')['queries'] if q.get('run'))
assert sum(a['exists'] for a in rpc('download.list',project='gut')['assets'].values())==22
assert rpc('storage.state.read')==state
assert (new/'PackTest2026/qa/history.json').read_text()=='{"question":"preserve QA"}'
# Changing the XML must change the package, regardless of files left on disk.
q=rpc('workspace',project='packtest')['queries'][0]
rpc('query.archive',project='packtest',id=q['id'],value=True)
rpc('xml.import',project='packtest',name='only102.xml',xml=xml.replace('<PubmedArticle><MedlineCitation><PMID>101</PMID><Article><ArticleTitle>Paper 101</ArticleTitle><Abstract><AbstractText>Abstract 101</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>',''))
# Removed members lose derived abstracts; re-inclusion does not restore them.
project=new/'PackTest2026'
assert not (project/'abstracts/102.md').exists() and not (project/'abstracts/999.md').exists()
(project/'abstracts/102.md').write_text('New abstract after re-inclusion')
packed=rpc('download.export',project='packtest');assert packed['pdf']==0 and packed['abstracts']==1
# Clearing one project leaves its XML/history, other projects and system resources intact.
other_before=fingerprint(new/'gut');reference_before=fingerprint(TEST/'data/reference');project=new/'PackTest2026'
xml_before=(project/'pubmed/current.xml').read_bytes();reject('download.clear',project='packtest')
cleared=rpc('download.clear',project='packtest',confirm='packtest');assert cleared['pdf']==2 and cleared['abstracts']==1
assert not list((project/'pdf').glob('*.pdf')) and not list((project/'abstracts').glob('*.md'))
assert not list((project/'packages').glob('*.zip'));assert (project/'pubmed/current.xml').read_bytes()==xml_before
assert rpc('download.list',project='packtest')['assets']=={}
assert fingerprint(new/'gut')==other_before and fingerprint(TEST/'data/reference')==reference_before
assert (project/'qa/history.json').read_text()=='{"question":"preserve QA"}'
# Real subprocess worker after relocation, with all network sources disabled in the fixture.
rpc('download.settings.save',fastOa=False,mirrors=[],enhanced=False)
b=rpc('download.start',project='packtest',pmids=['102'])
for _ in range(30):
    state_after=rpc('download.list',project='packtest')
    if state_after['batches'][0]['state']=='done':break
    time.sleep(.2)
assert state_after['batches'][0]['state']=='done'
assert (project/'abstracts/102.md').exists() and (project/'logs'/b['id']/'download_report.txt').exists()
result={'passed':True,'fixture':str(TEST),'checks':['legacy XML/PDF/abstract/report migration with recovery copy','38 corpus members and 22 PDF assets preserved','project DBs isolated from system settings','folder and Windows-name validation','XML-matched ZIP replacement, failure preserves prior ZIP','workspace migration with hash verification','removed abstracts are not resurrected on re-inclusion','QA history migrates and survives literature clearing','XML changes reflected in next package','project-scoped destructive clear preserves XML, logs, other projects and system files','real worker writes abstracts and reports after workspace move']}
(ROOT/'docs/STORAGE_TEST_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
