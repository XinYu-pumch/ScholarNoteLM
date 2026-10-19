"""Integration tests against the actual Rust research engine; fixtures stay under tmp/."""
import base64, json, os, pathlib, shutil, subprocess, tempfile, threading, zipfile, sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape
ROOT=pathlib.Path(__file__).resolve().parents[1]
TEST=pathlib.Path(tempfile.mkdtemp(prefix='research-integration-',dir=ROOT/'tmp'))
(TEST/'data/reference/jcr').mkdir(parents=True)
shutil.copy(ROOT/'services/reference/jcr/default-2025.xlsx',TEST/'data/reference/jcr/default-2025.xlsx')
(TEST/'runtimes').mkdir(exist_ok=True);(TEST/'runtimes/downloader').symlink_to(ROOT/'runtimes/downloader',target_is_directory=True);(TEST/'services').symlink_to(ROOT/'services',target_is_directory=True)
ENV=dict(os.environ,SCHOLARNOTELM_ROOT=str(TEST))
BIN=ROOT/'cache/tauri-target/debug/research-cli'
checks=[]
def rpc(action,**args):
    r=subprocess.run([str(BIN)],input=json.dumps(dict(action=action,args=args)),text=True,capture_output=True,env=ENV,check=True)
    v=json.loads(r.stdout)
    if not v['ok']:raise RuntimeError(v['error'])
    return v['data']
def failure(action,**args):
    try:rpc(action,**args)
    except RuntimeError as e:return str(e)
    raise AssertionError('expected failure')
def workbook(name,rows):
    p=TEST/name
    cols=['Journal','ISSN','eISSN','Category','Total citation','JIF','Quartile','JIF rank']
    xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
    for i,row in enumerate([cols]+rows,1):
        xml+='<row r="%s">'%i
        for j,v in enumerate(row):xml+='<c r="%s%s" t="inlineStr"><is><t>%s</t></is></c>'%(chr(65+j),i,escape(str(v)))
        xml+='</row>'
    xml+='</sheetData></worksheet>'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="JCR" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',xml)
    return p
def upload(p):return rpc('jcr.upload',name=p.name,base64=base64.b64encode(p.read_bytes()).decode())
def xml(ids):return '<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{i}</PMID><Article><ArticleTitle>Fixture {i}</ArticleTitle><Journal><Title>Fixture Journal</Title><ISSN>1234-5678</ISSN></Journal></Article></MedlineCitation></PubmedArticle>' for i in ids)+'</PubmedArticleSet>'
try:
    d=rpc('settings');assert d['jcr']['rows']==22249 and d['jcr']['warningCount']==2303
    checks.append('BADR JCR: 22249 rows; pandas-compatible NA handling')
    version=d['jcr']['version'];bad=workbook('bad.xlsx',[['Test','1234-5678','','Category',0,2,'Q5',1]])
    assert 'Q5' in failure('jcr.upload',name=bad.name,base64=base64.b64encode(bad.read_bytes()).decode())
    assert rpc('settings')['jcr']['version']==version
    assert 'Excel' in failure('jcr.upload',name='corrupt.xlsx',base64=base64.b64encode(b'broken').decode())
    checks.append('Invalid/corrupt JCR never replaces active reference')
    multi=workbook('multi.xlsx',[['Fixture Journal','1234-5678','','Category A',0,2,'Q4',1],['Fixture Journal','1234-5678','','Category B',0,2,'Q1',1]])
    upload(multi)
    a=rpc('xml.import',project='test',name='A',xml=xml([101,102,103]));aid=a['queries'][0]['id']
    b=rpc('xml.import',project='test',name='B',xml=xml([103,104]));assert b['corpus']['included']==4
    def update_filter(q,**patch):
        f=dict(q['filters']);f.update(patch)
        return rpc('query.save',project='test',id=q['id'],revision=q['revision'],name=q['name'],text=q['text'],filters=f)
    filtered=update_filter(b['queries'][0],jcr=True,quartiles=['Q1'],unknown='exclude');assert filtered['corpus']['included']==4;assert len(filtered['corpus']['papers'][0]['jcr'])==2
    only_b=update_filter(filtered['queries'][0],quartiles=['Q2']);assert only_b['corpus']['included']==2
    assert [p['pmid'] for p in only_b['corpus']['papers'] if p['included']]==['103','104']
    none=update_filter(only_b['queries'][1],jcr=True,quartiles=['Q2'],unknown='exclude');assert none['corpus']['included']==0
    reset=update_filter(none['queries'][0],jcr=False);update_filter(reset['queries'][1],jcr=False)
    after=rpc('query.archive',project='test',id=aid,value=True);assert [p['pmid'] for p in after['corpus']['papers']]==['103','104']
    assert rpc('query.archive',project='test',id=aid,value=False)['corpus']['included']==4
    checks.append('Multi-category JCR; filtering; PMID dedup; archive/restore; preserved snapshots')
    q=rpc('query.save',project='test',name='Draft',text='microglia[tiab]')['queries'][-1]
    rpc('query.save',project='test',id=q['id'],revision=q['revision'],name='Draft 2',text='microglia[tiab] AND brain[tiab]')
    assert '更新' in failure('query.save',project='test',id=q['id'],revision=q['revision'],name='Old draft',text='cancer')
    assert rpc('workspace',project='test')['corpus']['included']==4
    assert failure('workspace',project='../escape')
    row=rpc('query.create',project='test')['queries'][-1];assert row['text']=='' and row['filters']['limit']==30 and row['filters']['sort']=='relevance' and row['filters']['quartiles']==[] and not row['filters']['jcr']
    assert failure('query.run',project='test',id=row['id'])=='请先填写检索式'
    checks.append('Optimistic query revisions, blank inline row, per-query defaults and project path validation')
    # Reproduce v0.2 storage, migrate on open, and verify fresh defaults remain independent.
    legacy=rpc('query.create',project='migration')['queries'][0]
    old_filters=dict(legacy['filters'],limit=77,start='2021-01-01',quartiles=['Q2'],jcr=True)
    conn=sqlite3.connect(TEST/'workspace/migration/metadata/research.sqlite3')
    conn.execute("DELETE FROM settings WHERE key=?",('queryFilters:'+legacy['id'],))
    conn.execute("INSERT INTO settings VALUES(?,?)",('filters:migration',json.dumps(old_filters)))
    old_messages=[dict(role='user',text='旧问题',created=1),dict(role='assistant',text='旧回答',created=2)]
    conn.execute("INSERT INTO conversations VALUES(?,?)",('migration',json.dumps(old_messages)))
    conn.commit();conn.close()
    migrated=rpc('workspace',project='migration');assert migrated['queries'][0]['filters']==old_filters
    assert rpc('chat.get',project='migration',id='legacy-migration')['messages']==old_messages
    fresh=rpc('query.create',project='migration')['queries'][-1];assert fresh['filters']['limit']==30 and fresh['filters']['quartiles']==[]
    checks.append('v0.2 project filters and conversation migrate losslessly; fresh query uses new defaults')
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            assert self.path=='/custom/v1/models';self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"fixture-model"}]}')
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            assert self.path=='/custom/v1/chat/completions'
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"choices":[{"message":{"content":"connection OK"}}]}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    profile=dict(id='',name='Fixture',baseUrl=f'http://127.0.0.1:{server.server_port}/custom/v1',model='fixture-model',apiKey='TEST-SECRET-NOT-REAL',temperature=.2,sendTemperature=False,maxTokens=4096,tokenField='max_completion_tokens',timeout=30)
    saved=rpc('profile.save',profile=profile);assert 'apiKey' not in saved and saved['hasKey']
    assert rpc('llm.models',profile=saved)==['fixture-model'];assert rpc('llm.test',profile=saved)['reply']=='connection OK'
    assert 'temperature' not in requests[0] and 'max_completion_tokens' not in requests[0] and 'max_tokens' not in requests[0] and requests[0]['stream']
    assert 'TEST-SECRET' not in json.dumps(rpc('settings'))
    saved.update(apiKey='',name='Renamed');assert rpc('profile.save',profile=saved)['hasKey']
    saved['clearKey']=True;assert not rpc('profile.save',profile=saved)['hasKey']
    server.shutdown();checks.append('LLM endpoints, model listing, real request protocol, secret redaction/preservation/clearing')
    result=dict(passed=True,checks=checks,testRoot=str(TEST))
    (ROOT/'docs/RESEARCH_TEST_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
finally:
    shutil.rmtree(TEST)
