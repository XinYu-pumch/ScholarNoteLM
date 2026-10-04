import sys,unittest,struct
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import vector_chunks as chunks,vector_service as vectors,review_retrieval as review,qa_service as qa
import engine as e
from test_vectors import VectorTests

class RecallPolicyTests(unittest.TestCase):
 setUp=VectorTests.setUp
 tearDown=VectorTests.tearDown
 xml=VectorTests.xml
 def record(self,text,kind='heading',ident='x'):
  return {'id':ident,'text':text,'metadata':{'blockType':kind}}
 def test_visible_characters_and_only_headings_are_filtered(self):
  for n,allowed in [(99,False),(100,True)]:
   text='# <span id="page-1"></span>**['+'文'*n+'](https://example.org/'+'x'*300+')**'
   self.assertEqual(chunks.recall_allowed(self.record(text)),allowed)
   self.assertEqual(qa.evidence_allowed(self.record(text)),allowed)
  for kind in ['paragraph','caption','table','unknown']:
   self.assertTrue(chunks.recall_allowed(self.record('A short result.',kind)))
  self.assertTrue(chunks.recall_allowed(self.record('# Result\nA short result.','paragraph')))
  self.assertFalse(chunks.recall_allowed(self.record(' ')))
 def test_review_filters_before_topk_and_does_not_change_records(self):
  records=[self.record('# immune','heading','short'),self.record('# '+('immune '*20),'heading','long'),self.record('immune response','paragraph','body')]
  with patch.object(review,'APIRecall') as api:
   api.return_value.recall.return_value=[(0,.9),(1,.8)]
   obj=review.Retriever(e.ROOT,e.ROOT,records,lambda:None,lambda _:None,{'method':'api'},e)
  self.assertEqual({r['id'] for r in obj.retrieve('immune',2,2)},{'long','body'})
  self.assertEqual(len(records),3)
  with patch.object(review,'APIRecall') as api:
   empty=review.Retriever(e.ROOT,e.ROOT,records[:1],lambda:None,lambda _:None,{'method':'api','reranker':'qwen3'})
   self.assertEqual(empty.retrieve('immune',50,7),[]);api.assert_not_called()
 def make_corpus(self):
  self.xml();original=chunks.source
  text='\n\n'.join(['# immune '+str(i) for i in range(130)]+['immune finding.','immune conclusion.'])
  def source(*args):return text,original(*args)[1]
  with patch.object(chunks,'source',side_effect=source):chunks.sync(e)
  with chunks.connect(e) as db:
   doc=chunks.documents(e)[0];records=chunks.records_for(db,doc['version'],doc['metadata'])
  return doc,records
 def test_keyword_candidates_are_refilled_and_neighbors_preserved(self):
  _,records=self.make_corpus()
  with patch.object(chunks,'sync'):
   result=vectors.search(e,{'query':'immune','method':'keyword','limit':2})['results']
  self.assertEqual({r['text'] for r in result},{'immune finding.','immune conclusion.'})
  first=next(r for r in result if r['text']=='immune finding.')
  self.assertIn('# immune 129',[n['text'] for n in first['neighbors']])
  self.assertEqual(len(records),132)
 def test_semantic_filter_applies_before_limit(self):
  doc,records=self.make_corpus();doc['indexed']=True
  allowed=[r for r in records if chunks.recall_allowed(r)];blocked=[r for r in records if not chunks.recall_allowed(r)]
  self.assertTrue(allowed and blocked)
  cfg=vectors.config(e);pid=vectors.profile(cfg)
  with chunks.connect(e) as db:
   db.execute('INSERT INTO profiles VALUES(?,?,?)',(pid,2,'{}'))
   # Excluded chunks match the query best; they must still never be ranked.
   for r in records:db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?)',(pid,chunks.digest(chunks.embedding_text(r)),2,struct.pack('<2f',*((1.,0.) if r in blocked else (.6,.8)))))
  with patch.object(chunks,'sync'),patch.object(chunks,'documents',return_value=[doc]),patch.object(vectors,'embed',return_value=[[1.,0.]]):
   result=vectors.search(e,{'query':'immune','method':'semantic','limit':len(records)})['results']
  self.assertEqual({r['id'] for r in result},{r['id'] for r in allowed})
  self.assertAlmostEqual(result[0]['distance'],.4,places=5)
 def test_recall_policy_changes_prepare_signature_not_embedding_profile(self):
  cfg={'method':'bm25','reranker':'none'};before=review.signature(e.ROOT,cfg);profile=vectors.profile(vectors.config(e))
  with patch.object(chunks,'HEADING_MIN_CHARS',120):
   self.assertNotEqual(review.signature(e.ROOT,cfg),before)
   self.assertEqual(vectors.profile(vectors.config(e)),profile)
 def test_qa_reuses_existing_vectors_with_shared_filter_without_rebuilding(self):
  doc,records=self.make_corpus();pid=vectors.profile(vectors.config(e))
  with chunks.connect(e) as db:
   for r in records:db.execute('INSERT INTO embeddings VALUES(?,?,?,?)',(pid,chunks.digest(chunks.embedding_text(r)),2,struct.pack('<ff',1.,0.)))
  with patch.object(qa,'documents',return_value=[doc]),patch.object(chunks,'sync',side_effect=AssertionError('read-only QA')),patch.object(vectors,'embed',side_effect=AssertionError('reuse cached vectors')):
   found,cached,_,coverage=qa.corpus(e)
  self.assertEqual([r['text'] for r in found],['immune finding.','immune conclusion.'])
  self.assertEqual(len(cached),2);self.assertEqual(coverage['searchableChunks'],2)

if __name__=='__main__':unittest.main()
