import sys,json,tempfile,unittest,time,struct
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,vector_service as v,vector_chunks as c,corpus_files as f,embedding_limits as limits,adaptive_embedding as adaptive
class AdaptiveTests(unittest.TestCase):
 def setUp(self):
  self.old=e.ROOT,e.PROJECT;self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'adaptive'
  self.cfg={**v.DEFAULTS,'baseUrl':'https://example.test/v1','apiKey':'secret','rpm':1800,'tpm':450000}
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def xml(self,ids=('1','2')):
  body='\n\n'.join('Unique paragraph '+str(i)+' content.' for i in range(100))
  e.atomic(f.base(e)/'pubmed/current.xml','<PubmedArticleSet>'+''.join('<PubmedArticle><MedlineCitation><PMID>'+p+'</PMID><Article><ArticleTitle>Fixture</ArticleTitle><Abstract><AbstractText>'+body+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for p in ids)+'</PubmedArticleSet>')
 def test_partial_admission_reconciliation_and_shared_rolling_window(self):
  a=limits.Limiter(e.ROOT,self.cfg);b=limits.Limiter(e.ROOT,self.cfg)
  with patch.object(limits.time,'time',return_value=1000):first=a.reserve_batch(32);self.assertEqual(first[1],32)
  with patch.object(limits.time,'time',return_value=1001):second=b.reserve_batch(32);self.assertEqual(second[1],22)
  with patch.object(limits.time,'time',return_value=1002):self.assertIsNone(a.reserve_batch(32))
  a.reconcile(first[0],{'prompt_tokens':5000})
  with patch.object(limits.time,'time',return_value=1003):self.assertEqual(b.reserve_batch(32)[1],32)
  with a.db() as db:self.assertLessEqual(db.execute('SELECT SUM(tokens) FROM requests').fetchone()[0],450000)
  with patch.object(limits.time,'time',return_value=1064):self.assertEqual(a.reserve_batch(32)[1],32)
 def test_dispatch_and_window_grace_do_not_expire_budget_early(self):
  limiter=limits.Limiter(e.ROOT,{**self.cfg,'tpm':8192})
  with patch.object(limits.time,'time',return_value=1000):ident,_=limiter.reserve_batch(1)
  with patch.object(limits.time,'time',return_value=1000.3):limiter.mark_dispatched(ident)
  with patch.object(limits.time,'time',return_value=1060.5):self.assertIsNone(limiter.reserve_batch(1))
  with patch.object(limits.time,'time',return_value=1061.31):self.assertEqual(limiter.reserve_batch(1)[1],1)
 def test_variable_costs_pack_to_remaining_quota(self):
  a=limits.Limiter(e.ROOT,{**self.cfg,'tpm':10000})
  with patch.object(limits.time,'time',return_value=1000):
   reservation,count=a.reserve_batch(32,costs=[3000,4000,4000]);self.assertEqual(count,2)
  with patch.object(limits.time,'time',return_value=1001):
   self.assertEqual(a.reserve_batch(32,costs=[2000,3000])[1],1)
  with a.db() as db:self.assertEqual(db.execute('SELECT SUM(tokens) FROM requests').fetchone()[0],9000)
 def test_cross_document_dedup_persist_all_owners_and_resume(self):
  self.xml();c.sync(e);out=f.folder(e,'logs/test');notifications=[];calls=[]
  def embed(texts,cfg,**kw):
   calls.extend(texts);usage={'prompt_tokens':len(texts)*10};limits.Limiter(e.ROOT,cfg).reconcile(kw['reservation'],usage)
   kw['on_response']({'at':time.time(),'seconds':.3,'count':len(texts),'reserved':8192*len(texts),'status':200,'usage':usage})
   return [[1.,2.,float(len(text))] for text in texts]
  with patch.object(v,'embed',side_effect=embed):adaptive.populate(e,self.cfg,['1','2'],lambda:None,notifications.append,out)
  self.assertEqual(len(calls),100);self.assertEqual(len(set(calls)),100)
  with c.connect(e) as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0],100)
   self.assertEqual(db.execute('SELECT COUNT(*) FROM embedding_owners').fetchone()[0],200)
  with patch.object(v,'embed',side_effect=AssertionError('cached input sent twice')):adaptive.populate(e,self.cfg,['1','2'],lambda:None,notifications.append,out)
  self.assertEqual(notifications[-1]['completed'],100)
  self.assertNotIn('secret',(out/'embedding-requests.jsonl').read_text())
 def test_scoped_sync_preserves_other_members_and_detects_changes(self):
  self.xml();c.sync(e);before={d['pmid']:d['version'] for d in c.documents(e)}
  self.xml(['2']);c.sync(e,['1']);self.assertEqual([d['pmid'] for d in c.documents(e)],['2']);self.assertEqual(c.documents(e,pmid='2')[0]['version'],before['2'])
 def test_failed_response_is_not_persisted_as_complete(self):
  self.xml();c.sync(e)
  with patch.object(v,'embed',side_effect=ValueError('HTTP failure')):
   with self.assertRaisesRegex(ValueError,'HTTP failure'):adaptive.populate(e,self.cfg,['1','2'],lambda:None,lambda x:None,f.folder(e,'logs/test'))
  with c.connect(e) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0],0)
if __name__=='__main__':unittest.main()
