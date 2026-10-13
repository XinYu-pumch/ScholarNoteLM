"""Disposable Design System fixture. Never reads the user's config or workspace."""
import json,os,sqlite3,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/downloader'))
import storage
root=Path(tempfile.mkdtemp(prefix='design-system-',dir=ROOT/'tmp'))
for name in ('services','runtimes','models'):(root/name).symlink_to(ROOT/name,target_is_directory=True)
(root/'tmp').mkdir();storage.initialize(root)
project={'id':'design_fixture','name':'设计系统验收','description':'隔离测试，虚构材料','color':'purple','papers':[],'messages':[],'sections':[],'notes':{},'tasks':[]}
storage.register(root,{'project':project['id'],'folder':'DesignFixture','data':project})
storage.write_state(root,{'version':1,'theme':'light','active':project['id'],'projects':[project]})
cfg=root/'data/research/research.sqlite3';cfg.parent.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(cfg) as c:
 c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
 c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('meshAuto','false'))
def rpc(action,**args):
 r=subprocess.run([str(ROOT/'cache/tauri-target/debug/research-cli')],input=json.dumps({'action':action,'args':{'project':project['id'],**args}}),text=True,capture_output=True,env={**os.environ,'SCHOLARNOTELM_ROOT':str(root)},check=True)
 result=json.loads(r.stdout)
 if not result['ok']:raise RuntimeError(result.get('error'))
 return result['data']
xml='<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{900000+i}</PMID><Article><ArticleTitle>设计验收文献 {i} — 长标题与摘要阅读测试</ArticleTitle><Abstract><AbstractText>'+('This is fictional evidence for interface testing. '*30)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for i in range(1,25))+'</PubmedArticleSet>'
rpc('xml.import',name='UI fixture XML',xml=xml)
rpc('query.create',name='示例检索式',text='fixture[Title]')
rpc('review.create',name='设计综述',topic='虚构材料的机制与证据')
rpc('review.import',name='设计综述',revision=0,csv='Serial,Title\n1,研究背景\n1.1,研究目标\n1.1.1,细胞机制与长标题排版验收\n1.2,证据局限\n2,未来方向\n')
(root/'.design-system-fixture').write_text('Disposable UI fixture; no real model calls.\n')
print(root)
