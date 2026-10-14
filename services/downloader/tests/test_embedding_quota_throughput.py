"""Quota admission and delayed-success throughput, with no remote API calls."""
import hashlib,importlib.util,json,sys,tempfile,time,threading,unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import adaptive_embedding as adaptive,embedding_limits as limits
import embedding_controller as controller,embedding_token_budget as budget,vector_service as v

class QuotaThroughputTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]/'tmp');self.root=Path(self.tmp.name);self.e=SimpleNamespace(ROOT=self.root)
  self.cfg={**v.DEFAULTS,'baseUrl':'https://api.jina.ai/v1/embeddings','model':'jina-embeddings-v4','rpm':600,'tpm':600000,'batchSize':1,'concurrency':1}
 def tearDown(self):self.tmp.cleanup()
 def test_actual_usage_drives_overlap_despite_manual_values_and_slow_responses(self):
  lock=threading.Lock();flight=[0,0];events=[];saved=[];updates=[]
  def embed(texts,cfg,**kw):
   ledger=limits.Limiter(self.root,cfg);at=ledger.mark_dispatched(kw['reservation'])
   with lock:flight[0]+=1;flight[1]=max(flight)
   try:
    time.sleep(.4)
    usage={'total_tokens':125*len(texts)}
    ledger.reconcile(kw['reservation'],usage)
    event={'at':at,'seconds':.4,'count':len(texts),'status':200,'reserved':kw['reserved_tokens'],'usage':usage}
    with lock:events.append(event)
    kw['on_response'](event);return [[1.,2.] for _ in texts]
   finally:
    ledger.finish(kw['reservation'])
    with lock:flight[0]-=1
  began=time.monotonic()
  # Budgets exceed actual usage deliberately, as with conservative tokenizers.
  with patch.object(budget,'jina_costs',return_value=[250]*600),patch.object(v,'embed',side_effect=embed),patch.object(controller,'OBSERVATION_SECONDS',.3):
   adaptive.run_inputs(self.e,self.cfg,[(str(i),'body') for i in range(600)],lambda:None,updates.append,self.root,lambda group,_:saved.extend(k for k,_ in group),'auto')
  elapsed=time.monotonic()-began
  self.assertEqual(len(set(saved)),600);self.assertEqual(len(saved),600)
  self.assertGreaterEqual(flight[1],4)
  self.assertLess(elapsed,15) # Serial responses alone would require >=30 seconds.
  self.assertGreater(max(r['count'] for r in events),1)
  self.assertTrue(any(u['concurrency']>1 for u in updates))
  # No overlapping requests bypass either ledger, including reservations.
  for event in events:
   window=[x for x in events if event['at']-60<x['at']<=event['at']]
   self.assertLessEqual(len(window),600)
   self.assertLessEqual(sum(x['reserved'] for x in window),600000)
 def test_pending_request_does_not_release_budget_after_one_minute(self):
  cfg={**self.cfg,'tpm':10000,'timeout':120};ledger=limits.Limiter(self.root,cfg)
  with patch.object(limits.time,'time',return_value=1000):
   ident,_=ledger.reserve_batch(1,costs=[10000]);ledger.mark_dispatched(ident)
  with patch.object(limits.time,'time',return_value=1062):self.assertIsNone(ledger.reserve_batch(1,costs=[1]))
  ledger.reconcile(ident,{'total_tokens':5000});ledger.finish(ident)
  with patch.object(limits.time,'time',return_value=1063):self.assertEqual(ledger.reserve_batch(1,costs=[10000])[1],1)
 def test_abandoned_request_eventually_expires(self):
  ledger=limits.Limiter(self.root,{**self.cfg,'timeout':10,'tpm':10000})
  with patch.object(limits.time,'time',return_value=1000):
   ident,_=ledger.reserve_batch(1,costs=[10000]);ledger.mark_dispatched(ident)
  with patch.object(limits.time,'time',return_value=1072):self.assertEqual(ledger.reserve_batch(1,costs=[10000])[1],1)
 def test_unknown_usage_retains_full_reservation(self):
  ledger=limits.Limiter(self.root,{**self.cfg,'tpm':10000})
  with patch.object(limits.time,'time',return_value=1000):ident,_=ledger.reserve_batch(1,costs=[10000])
  ledger.reconcile(ident,{});ledger.finish(ident)
  with patch.object(limits.time,'time',return_value=1002):self.assertIsNone(ledger.reserve_batch(1,costs=[1]))
 def test_two_schedulers_share_free_tier_quota_across_rolling_windows(self):
  cfg={**self.cfg,'rpm':100,'tpm':100000};a=limits.Limiter(self.root,cfg);b=limits.Limiter(self.root,cfg)
  sent=[];inflight=[];count=0
  for tick in range(600):
   now=1000+tick*.3
   with patch.object(limits.time,'time',return_value=now):
    for due,ledger,ident,actual in list(inflight):
     if due<=now:
      ledger.reconcile(ident,{'total_tokens':actual});ledger.finish(ident);inflight.remove((due,ledger,ident,actual))
    ledger=a if tick%2 else b
    admission=ledger.reserve_batch(3,costs=[500,1500,3000])
    if admission:
     ident,n=admission;reserved=sum([500,1500,3000][:n]);actual=reserved//2
     ledger.mark_dispatched(ident);sent.append((now,actual));inflight.append((now+5,ledger,ident,actual));count+=1
    with ledger.db() as db:
     self.assertLessEqual(db.execute('SELECT SUM(tokens) FROM requests').fetchone()[0] or 0,100000)
    window=[r for r in sent if now-60<r[0]<=now]
    self.assertLessEqual(len(window),100);self.assertLessEqual(sum(r[1] for r in window),100000)
  self.assertGreater(count,100) # Continues making progress beyond the first window.
 def test_tokenizer_scope_never_leaks_across_models_providers_or_revisions(self):
  for delta in [{'model':'jina-embeddings-v3'},{'modelRevision':'custom'},{'baseUrl':'https://example.test/v1'}]:
   with patch('httpx.stream',side_effect=AssertionError('must not download')):
    self.assertIsNone(budget.jina_costs(self.root,{**self.cfg,**delta},['text'],lambda:None))
 @unittest.skipUnless(importlib.util.find_spec('tokenizers'),'Tokenizer lives in the index worker runtime')
 def test_tokenizer_download_failure_and_corruption_fall_back_without_partial_asset(self):
  import httpx
  for error in [httpx.ConnectError('offline'),ValueError('invalid asset')]:
   with patch('httpx.stream',side_effect=error):
    self.assertIsNone(budget.jina_costs(self.root,self.cfg,['text'],lambda:None))
   directory=self.root/'cache/embedding-tokenizers/jina-embeddings-v4'
   self.assertFalse(directory.exists() and list(directory.iterdir()))
  @contextmanager
  def corrupt(*args,**kwargs):
   yield SimpleNamespace(raise_for_status=lambda:None,iter_bytes=lambda _:iter([b'corrupt tokenizer']))
  with patch('httpx.stream',side_effect=corrupt):
   self.assertIsNone(budget.jina_costs(self.root,self.cfg,['text'],lambda:None))
  self.assertFalse(list(directory.iterdir()))
 @unittest.skipUnless(importlib.util.find_spec('tokenizers'),'Tokenizer lives in the index worker runtime')
 def test_cached_tokenizer_counts_entire_text_and_checks_digest(self):
  from tokenizers import Tokenizer,models,pre_tokenizers
  tokenizer=Tokenizer(models.WordLevel({'[UNK]':0,'word':1},unk_token='[UNK]'));tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
  # Stored truncation must never silently shorten the budget or API input.
  tokenizer.enable_truncation(2)
  path=self.root/'cache/embedding-tokenizers/jina-embeddings-v4/tokenizer.json';path.parent.mkdir(parents=True);tokenizer.save(str(path))
  digest=hashlib.sha256(path.read_bytes()).hexdigest()
  with patch.object(budget,'JINA_V4_SHA256',digest),patch('httpx.stream',side_effect=AssertionError('cache should be used')):
   self.assertEqual(budget.jina_costs(self.root,self.cfg,['word '*100],lambda:None),[113])
 def test_stop_during_tokenizer_setup_propagates(self):
  def stop():raise InterruptedError('stopped')
  with self.assertRaises(InterruptedError):budget.jina_costs(self.root,self.cfg,['text'],stop)

if __name__=='__main__':unittest.main()
