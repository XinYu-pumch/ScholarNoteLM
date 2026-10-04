"""Isolated acceptance: mock Zotero collections + real PubMed, no user project writes."""
import json,os,sys,threading,subprocess,time,hashlib,sqlite3,xml.etree.ElementTree as ET
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/downloader'))
sys.path.insert(0,str(ROOT/'services/downloader/tests'))
from pdf_fixture import pdf
import engine as e
original=ROOT/'workspace/PrimaryMN/pubmed/current.xml';original_hash=hashlib.sha256(original.read_bytes()).hexdigest()
records=[]
for a in ET.parse(original).getroot():
    doi=a.findtext('./PubmedData/ArticleIdList/ArticleId[@IdType="doi"]')
    if doi:records.append((a.findtext('./MedlineCitation/PMID'),doi))
assert len(records)==253
folder=ROOT/'experiments'/f'zotero-acceptance-{time.time_ns()}'
folder.mkdir(parents=True);(folder/'services').symlink_to(ROOT/'services',target_is_directory=True);(folder/'runtimes').symlink_to(ROOT/'runtimes',target_is_directory=True);(folder/'tmp').mkdir()
fixture=folder/'fixture.pdf';fixture.write_bytes(pdf('Acceptance fixture only'))
items=[{'key':f'ITEM{i:04d}','data':{'key':f'ITEM{i:04d}','itemType':'journalArticle','title':f'Fixture {pmid}','DOI':doi}} for i,(pmid,doi) in enumerate(records)]
first_only=False
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        route=urlsplit(self.path);q=parse_qs(route.query);path=route.path;headers={};data=None
        if path.endswith('/collections'):
            data=[{'key':'COLLECT1','data':{'name':'Acceptance','parentCollection':False}},{'key':'COLLECT2','data':{'name':'Nested','parentCollection':'COLLECT1'}}]
        elif '/collections/' in path and path.endswith('/items/top'):
            data=items[:1] if first_only else items[:130] if 'COLLECT1' in path else items[120:]
        elif path.endswith('/children'):
            data=[{'key':'ATTACH01','data':{'key':'ATTACH01','itemType':'attachment','parentItem':'ITEM0000','title':'Full Text PDF','linkMode':'linked_file','contentType':'application/pdf','filename':'main.pdf','url':''}}] if 'ITEM0000' in path else []
        elif path.endswith('/file/view/url'):
            body=fixture.as_uri().encode()
        elif '/items/ITEM' in path:
            body=json.dumps(items[int(path.rsplit('ITEM',1)[1])]).encode()
        else:self.send_error(404);return
        if data is not None:
            headers={'Total-Results':str(len(data)),'Last-Modified-Version':'1'};start=int(q.get('start',['0'])[0]);limit=int(q.get('limit',['100'])[0]);body=json.dumps(data[start:start+limit]).encode()
        self.send_response(200)
        for k,v in headers.items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
e.ROOT=folder;e.PROJECT='acceptance'
with e.db(system=True) as db:db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('config',json.dumps({'zoteroAddress':f'localhost:{server.server_port}'})))
def rpc(action,**args):
    r=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':{'project':'acceptance',**args}}),capture_output=True,text=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(folder)},timeout=180)
    data=json.loads(r.stdout)
    if not data['ok']:raise RuntimeError(data['error'])
    return data['data']
def run_import():
    preview=rpc('zotero.preview',collection='COLLECT1');print('preview',preview['total'],preview['uniqueDois'],flush=True)
    j=rpc('zotero.start',preview=preview['id']);deadline=time.time()+600;last=''
    while time.time()<deadline:
        j=rpc('zotero.status')
        if j['stage']!=last:print(j['stage'],flush=True);last=j['stage']
        if j['state'] not in ('queued','running'):break
        time.sleep(2)
    assert j['state']=='completed',j.get('error',j)
    return j
try:
    rpc('workspace');job=run_import();assert job['matched']==253,job['matched']
    expected={p for p,d in records};w=rpc('workspace');assert {p['pmid'] for p in w['corpus']['papers'] if p['included']}==expected
    assert job['pdfImported']==1;first_only=True;second=run_import();assert second['pdfReused']==1
    w=rpc('workspace');assert len(w['queries'])==2;assert w['corpus']['included']==253
    assert hashlib.sha256(original.read_bytes()).hexdigest()==original_hash
    result={'first':{k:job[k] for k in ['id','state','total','matched','pdfImported','pdfReused']},'second':{k:second[k] for k in ['id','state','total','matched','pdfImported','pdfReused']},'pmidsExact':True,'sourceCount':2,'primaryMNUnchanged':True,'primaryMNSha256':original_hash}
    (folder/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True);print(folder,flush=True)
finally:server.shutdown()
