"""Create an isolated fixture for test-workspace-update-ui.mjs."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'services/downloader'),str(ROOT/'services/downloader/tests')]
import engine as e,storage,corpus_files as f,review_service as r
from test_scihub_retry import pdf
p=Path(sys.argv[1]).resolve()
if ROOT/'tmp' not in p.parents:raise ValueError('UI fixture must be inside tmp/')
p.mkdir(exist_ok=True);e.ROOT=p;e.PROJECT='UITest'
for name in ('services','runtimes','models'):(p/name).symlink_to(ROOT/name,target_is_directory=True)
project={'id':'UITest','name':'界面验证项目','description':'隔离测试数据','color':'purple','papers':[],'messages':[],'sections':[],'notes':{},'tasks':[]}
storage.register(p,{'project':'UITest','folder':'UITest','data':project});storage.write_state(p,{'version':1,'active':'UITest','theme':'light','projects':[project]})
cfg=storage.config(p);cfg['migrated']=True;e.write_json(p/'config/storage.json',cfg)
b=f.base(e);title='Long full title '+('Complete title words '*18)
e.atomic(b/'pubmed/current.xml','<PubmedArticleSet>'+''.join(f'<PubmedArticle><MedlineCitation><PMID>{i}</PMID><Article><ArticleTitle>{title if i==1 else "Abstract paper"}</ArticleTitle><Abstract><AbstractText>'+('Test source evidence. '*30)+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for i in [1,2])+'</PubmedArticleSet>')
e.atomic(b/'pdf/1.pdf',pdf());f.reconcile(e)
r.rpc(e,'create',{'name':'Existing','outlineSource':'file','fileName':'initial.csv','csv':'Serial,Title\n1,原始标题\n1.1,子标题\n','topic':'原始主题'})
