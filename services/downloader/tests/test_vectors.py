import ast,json,random,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e,corpus_files as f,vector_chunks as c,vector_service as v
class VectorTests(unittest.TestCase):
 def setUp(self):
  self.old=(e.ROOT,e.PROJECT);self.tmp=tempfile.TemporaryDirectory(dir=e.ROOT/'tmp');e.ROOT,e.PROJECT=Path(self.tmp.name),'test';self.base=f.base(e)
 def tearDown(self):e.ROOT,e.PROJECT=self.old;self.tmp.cleanup()
 def xml(self,body='Immune result. '*20):
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Title</ArticleTitle><Abstract><AbstractText>'+body+'</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
 def test_paragraph_split_is_balanced_at_period_and_preserves_offsets(self):
  text='  '+('a'*4400)+'. '+('b'*4300)+'.  '
  result=c.split(text);self.assertEqual(len(result),2);self.assertTrue(result[0]['text'].endswith('.'));self.assertLess(abs(result[0]['chars']-result[1]['chars']),150)
  for x in result:self.assertEqual(text[x['charStart']:x['charEnd']],x['text'])
 def test_recursive_split_and_no_period_fallback(self):
  for text in [('a'*9000),('中文😀 '*6000),('.123 '*5000),('Sentence content. '*2400)]:
   result=c.split(text);self.assertTrue(all(100<=x['chars']<=8192 for x in result));self.assertEqual(''.join(x['text'] for x in result).replace(' ',''),text.replace(' ',''))
   for x in result:self.assertEqual(text[x['charStart']:x['charEnd']],x['text'])
 def test_short_paragraph_and_long_paragraph_tail_are_kept(self):
  self.assertTrue(c.split('a'*99)[0]['accepted']);self.assertTrue(c.split('a'*100)[0]['accepted'])
  result=c.split('a'*8200);self.assertEqual([x['chars'] for x in result],[4100,4100]);self.assertTrue(all(x['accepted'] for x in result))
 def test_heading_with_body_in_same_paragraph_is_not_filtered_as_heading(self):
  s=c.split('# Results\n'+('Important result. '*20))[0]
  self.assertEqual(s['blockType'],'paragraph');self.assertEqual(s['sectionPath'],['Results'])
 def test_adaptive_setting_preserves_vector_identity_and_manual_limits(self):
  v.rpc(e,'settings.save',{'adaptive':True,'baseUrl':'http://127.0.0.1:1234/v1','rpm':1800,'tpm':450000,'autoIndex':False})
  saved=v.config(e);self.assertTrue(saved['adaptive']);self.assertEqual(saved['rpm'],1800)
  self.assertEqual(v.profile(saved),v.profile({**saved,'adaptive':False}))
  with self.assertRaises(ValueError):v.validated(e,{'adaptive':'yes'})
  with self.assertRaises(ValueError):v.validated(e,{'adaptive':True,'tpm':100})
 def test_auto_index_requires_configuration_and_respects_disabled(self):
  self.assertEqual(v.rpc(e,'auto',{})['state'],'not_configured')
  v.rpc(e,'settings.save',{'baseUrl':'http://127.0.0.1:1234/v1','autoIndex':False})
  with patch.object(v,'start',side_effect=AssertionError('must not start')):
   self.assertEqual(v.rpc(e,'auto',{})['state'],'disabled')
 def test_version_and_membership_invalidation_with_history(self):
  self.xml();c.sync(e);a=c.documents(e)[0];self.xml('Changed result. '*20);c.sync(e);b=c.documents(e)[0];self.assertNotEqual(a['version'],b['version'])
  with c.connect(e) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],2)
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet/>');c.sync(e);self.assertEqual(c.documents(e),[]);self.assertFalse((self.base/'vectors/chunks/redundant/123.jsonl').exists())
  with c.connect(e) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],0)
  self.xml();c.sync(e);self.assertNotEqual(c.documents(e)[0]['version'],a['version'])
  self.assertTrue((self.base/'vectors/chunks/123.jsonl').exists());self.assertFalse((self.base/'vectors/chunks/redundant/123.jsonl').exists())
 def test_invalid_xml_does_not_remove_current_documents(self):
  self.xml();c.sync(e);e.atomic(self.base/'pubmed/current.xml','<broken>')
  with self.assertRaises(Exception):c.sync(e)
  self.assertEqual(len(c.documents(e)),1)
 def test_metadata_and_title_are_not_added_to_actual_chunks(self):
  self.xml();c.sync(e)
  with c.connect(e) as db:
   d=c.documents(e)[0];r=c.records_for(db,d['version'],d['metadata'])[0]
   self.assertNotIn('Title',r['text']);self.assertEqual(r['text'],c.embedding_text(r));self.assertEqual(r['metadata']['title'],'Title');self.assertIsNone(r['metadata']['pdfPages'])
   self.assertEqual(r['metadata']['sourceKind'],'pubmed_abstract')
 def test_secret_only_in_system_config(self):
  v.rpc(e,'settings.save',{'baseUrl':'http://127.0.0.1:1234/v1','apiKey':'private-test-key'})
  self.assertNotIn('private-test-key',json.dumps(v.settings(e)));self.assertIn('private-test-key',(e.ROOT/'config/embedding.json').read_text())
  v.rpc(e,'settings.save',{'apiKey':''});self.assertEqual(v.config(e)['apiKey'],'private-test-key')
 def test_invalid_config_does_not_persist(self):
  for a in ({'concurrency':9},{'timeout':True},{'baseUrl':'https://u:p@host/'},{'baseUrl':'https://host/?key=x'}):
   with self.assertRaises(ValueError):v.validated(e,a)
  self.assertFalse((e.ROOT/'config/embedding.json').exists())
 def test_embedding_profile_separates_model_and_revision_but_not_secret(self):
  x={**v.DEFAULTS,'baseUrl':'https://example.org/v1'}
  self.assertEqual(v.profile(x),v.profile({**x,'apiKey':'new'}));self.assertNotEqual(v.profile(x),v.profile({**x,'modelRevision':'2'}))
 def test_keyword_search_works_without_api_and_excludes_removed(self):
  self.xml();r=v.search(e,{'query':'immune','method':'keyword'});self.assertEqual(len(r['results']),1)
  e.atomic(self.base/'pubmed/current.xml','<PubmedArticleSet/>');self.assertEqual(v.search(e,{'query':'immune','method':'keyword'})['results'],[])
 def test_index_input_ignores_metadata_but_changes_with_body(self):
  self.xml();c.sync(e)
  with c.connect(e) as db:
   d=c.documents(e)[0];r=c.records_for(db,d['version'],d['metadata']);before=c.input_signature(r)
   r[0]['metadata'].update(title='Changed',sectionPath=['Completely different topic'])
   self.assertEqual(c.input_signature(r),before)
   r[0]['text']='A different result.';self.assertNotEqual(c.input_signature(r),before)
 def test_title_augmented_index_is_not_reused(self):
  self.xml();c.sync(e);cfg={**v.DEFAULTS,'baseUrl':'https://example.test/v1'}
  with patch.object(c,'TEMPLATE','title-section-body-v1'):
   old_profile=v.profile(cfg)
  new_profile=v.profile(cfg);self.assertNotEqual(old_profile,new_profile)
  with c.connect(e) as db:
   d=c.documents(e)[0];records=c.records_for(db,d['version'],d['metadata'])
   old_input=c.digest(['title-section-body-v1',*[c.digest(r['metadata']['title']+'\n'+' > '.join(r['metadata']['sectionPath'])+'\n\n'+r['text']) for r in records]])
   db.execute('INSERT INTO indexed VALUES(?,?,?,?)',(old_profile,'123',d['version'],old_input))
  self.assertFalse(c.inspect_documents(e,new_profile)[0]['indexed'])
  self.assertFalse(c.inspect_documents(e,old_profile)[0]['indexed'])
