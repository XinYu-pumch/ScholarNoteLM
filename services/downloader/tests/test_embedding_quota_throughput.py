"""Quota admission and delayed-success throughput, with no remote API calls."""
import hashlib,importlib.util,json,math,sys,tempfile,time,threading,unittest
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
   with patch.object(Path,'read_bytes',side_effect=AssertionError('must not read tokenizer')):
    self.assertIsNone(budget.jina_costs(self.root,{**self.cfg,**delta},['text'],lambda:None))
 def test_bundled_tokenizer_has_pinned_checksum_and_attribution(self):
  path=budget.JINA_V4_ASSET
  self.assertEqual(path.stat().st_size,11421896)
  self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),budget.JINA_V4_SHA256)
  self.assertIn(budget.JINA_V4_REVISION,(path.parent/'NOTICE').read_text())
  self.assertTrue((path.parent/'LICENSE').is_file())
 @unittest.skipUnless(importlib.util.find_spec('tokenizers'),'Tokenizer lives in the index worker runtime')
 def test_missing_corrupt_or_oversized_resource_falls_back_without_network_or_cache(self):
  path=self.root/'tokenizer.json'
  with patch.object(budget,'JINA_V4_ASSET',path),patch('socket.socket.connect',side_effect=AssertionError('must stay offline')):
   self.assertIsNone(budget.jina_costs(self.root,self.cfg,['text'],lambda:None))
   path.write_bytes(b'corrupt tokenizer')
   self.assertIsNone(budget.jina_costs(self.root,self.cfg,['text'],lambda:None))
   with patch.object(budget,'MAX_ASSET_BYTES',1),patch.object(Path,'read_bytes',side_effect=AssertionError('must reject oversized asset before reading')):
    self.assertIsNone(budget.jina_costs(self.root,self.cfg,['text'],lambda:None))
  self.assertEqual(list(self.root.iterdir()),[path])
 @unittest.skipUnless(importlib.util.find_spec('tokenizers'),'Tokenizer lives in the index worker runtime')
 def test_tokenizer_counts_entire_text_without_stored_truncation(self):
  from tokenizers import Tokenizer,models,pre_tokenizers
  tokenizer=Tokenizer(models.WordLevel({'[UNK]':0,'word':1},unk_token='[UNK]'));tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
  # Stored truncation and padding must never change full-text budgets.
  tokenizer.enable_truncation(2);tokenizer.enable_padding(length=200)
  path=self.root/'tokenizer.json';tokenizer.save(str(path))
  digest=hashlib.sha256(path.read_bytes()).hexdigest()
  with patch.object(budget,'JINA_V4_ASSET',path),patch.object(budget,'JINA_V4_SHA256',digest):
   self.assertEqual(budget.jina_costs(self.root,self.cfg,['word '*100],lambda:None),[113])
 @unittest.skipUnless(importlib.util.find_spec('tokenizers'),'Tokenizer lives in the index worker runtime')
 def test_official_bundle_works_offline_with_empty_root_without_copying_assets(self):
  from tokenizers import Tokenizer
  texts=['Primary membranous nephropathy.','原发性膜性肾病 🧬','蛋白尿 proteinuria. '*3000]
  tokenizer=Tokenizer.from_file(str(budget.JINA_V4_ASSET));tokenizer.no_truncation();tokenizer.no_padding()
  expected=[math.ceil(len(tokenizer.encode(t).ids)*1.05)+8 for t in texts]
  with patch('socket.socket.connect',side_effect=AssertionError('must stay offline')):
   self.assertEqual(budget.jina_costs(self.root,self.cfg,texts,lambda:None),expected)
   self.assertEqual(budget.jina_costs(self.root/'another-root',self.cfg,texts,lambda:None),expected)
  self.assertGreater(expected[-1],8192)
  self.assertEqual(list(self.root.iterdir()),[])
 def test_stop_during_tokenizer_setup_propagates(self):
  def stop():raise InterruptedError('stopped')
  with self.assertRaises(InterruptedError):budget.jina_costs(self.root,self.cfg,['text'],stop)

if __name__=='__main__':unittest.main()
