import copy,json,sys,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import review_bundle as b,review_content as c,review_export as x,review_objects as obj
import test_review_bundle as fixtures

class ObjectTests(unittest.TestCase):
 def setUp(self):self.fx=fixtures.BundleTests();self.fx.setUp()
 def tearDown(self):self.fx.tearDown()
 def table(self,ident='T1'):
  return {'type':'table','table_id':ident,'title':'跨来源比较','columns':['项目','结果'],'rows':[['A','42 [E1] [R1]'],['B','7 [E2]']],'notes':'人群不同，不直接比较 [E1] [E2]。'}
 def decode(self,first,second=None):
  value=self.fx.output();value['sections'][1]['blocks']=first
  if second is not None:value['sections'][2]['blocks']=second
  return b.decode(value,self.fx.write(),self.fx.unit,{'model':'vision','visionModels':['vision']})
 def test_shared_table_numbering_forward_references_and_provenance(self):
  sections,errors=self.decode([{'type':'markdown','text':'见 {{ref:T1}} 与 {{ref:R1}}，另有图片 {{ref:R2}} [E1]。'}, {'type':'resource','resource_id':'R1'}],
    [self.table(),{'type':'resource','resource_id':'R2'}])
  self.assertFalse(errors);before=copy.deepcopy(sections)
  rendered=c.render_sections(sections,self.fx.bundle['resources'],self.fx.project)
  blocks=rendered[1]['displayBlocks'];table=rendered[2]['displayBlocks'][0]
  self.assertIn('[表 2](#'+table['anchor']+')',blocks[0]['text']);self.assertEqual(blocks[1]['label'],'表 1')
  self.assertEqual(table['label'],'表 2');self.assertEqual(rendered[2]['displayBlocks'][1]['label'],'图 1')
  self.assertEqual([r['id'] for r in sections[2]['citationRefs']],['E1','R1','E2','R2'])
  self.assertEqual(table['rows'][0][1],'42 (PMID: 12345678)');self.assertEqual(sections,before)
  self.assertIn('[E1] [R1]',sections[2]['sourceMarkdown'])
 def test_dangling_malformed_and_manual_numbers_rejected(self):
  for text in ['见 {{ref:T1}}','见 {{ref:R1}}','见 {{ref:R999}}','见 {{ref:E1}}','见 {{ref:r1}}','见图1','见表R1','See Figure 2','See Table 1','See [table](#obj_fake)']:
   with self.subTest(text=text):self.assertIn('a',self.decode([{'type':'markdown','text':text}])[1])
  # A source citation alone does not need, or create, an inserted resource.
  sections,errors=self.decode([{'type':'markdown','text':'依据 [R1]。'}]);self.assertFalse(errors)
  self.assertEqual(len(c.render_sections(sections,self.fx.bundle['resources'],self.fx.project)[1]['displayBlocks']),1)
 def test_table_shape_duplicate_ids_and_each_row_citations(self):
  for mutate in [lambda t:t['rows'].append(['short']),lambda t:t.update(columns=[]),lambda t:t.update(table_id='../bad'),lambda t:t.update(extra='bad'),lambda t:t['rows'][0].__setitem__(1,42)]:
   table=self.table();mutate(table)
   with self.assertRaises(ValueError):self.decode([table])
  for mutate in [lambda t:t['rows'][0].__setitem__(1,'42'),lambda t:t['rows'][0].__setitem__(1,'42 [E999]'),lambda t:t.update(title='表1'),lambda t:t.update(notes='<img src=x>'),lambda t:t.update(notes='见 {{ref:T9}}')]:
   table=self.table();mutate(table);self.assertIn('a',self.decode([table])[1])
  self.assertIn('b',self.decode([self.table()],[self.table()])[1])
  self.assertIn('a',self.decode([{'type':'resource','resource_id':'R1'}]*2)[1])
  self.assertIn('a',self.decode([{'type':'markdown','text':'| A | B |\n|---|---|\n| X | 42 [E1] |'}])[1])
 def test_html_word_md_links_have_real_unique_targets_and_safe_cells(self):
  table=self.table();table['rows'][0][0]='literal | delimiter\nnext line'
  sections,errors=self.decode([{'type':'markdown','text':'见 {{ref:T1}} [E1]。'},table,{'type':'resource','resource_id':'R2'}],
    [{'type':'markdown','text':'同一图片 {{ref:R2}} [R2]。'},{'type':'resource','resource_id':'R2'}])
  self.assertFalse(errors);rendered=c.render_sections(sections,self.fx.bundle['resources'],self.fx.project)
  blocks={n['serial']:s['displayBlocks'] for n,s in zip(self.fx.nodes,rendered)};body={n['serial']:s['markdown'] for n,s in zip(self.fx.nodes,rendered)}
  from bs4 import BeautifulSoup
  html=x.html_document('Test',self.fx.nodes,body,{},False,blocks);soup=BeautifulSoup(html,'html.parser')
  ids=[n['id'] for n in soup.select('figure[id]')];self.assertEqual(len(ids),len(set(ids)))
  for link in soup.select('a[href^="#obj_"]'):self.assertIsNotNone(soup.find(id=link['href'][1:]))
  self.assertEqual(len(soup.select('.body-table td')),4);self.assertIn('literal | delimiter',soup.get_text())
  # Repeated original image keeps its number, but each occurrence has its own anchor.
  figs=[b for bs in blocks.values() for b in bs if b['type']=='resource'];self.assertEqual(figs[0]['label'],figs[1]['label']);self.assertNotEqual(figs[0]['anchor'],figs[1]['anchor'])
  self.assertIn(figs[1]['anchor'],blocks['1.2'][0]['text'])
  md='\n'.join(c.markdown(bs,lambda block:'resources/test.png') for bs in blocks.values())
  self.assertNotIn('{{ref:',md);self.assertIn(r'literal \| delimiter',md)
  for ident in ids:self.assertIn('<a id="'+ident+'"></a>',md)
  dest=self.fx.project/'objects.docx';x.word_document(dest,'Test',self.fx.nodes,body,False,blocks)
  from lxml import etree
  with zipfile.ZipFile(dest) as z:xml=etree.fromstring(z.read('word/document.xml'))
  ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
  bookmarks=xml.xpath('//w:bookmarkStart/@w:name',namespaces=ns);refs=xml.xpath('//w:hyperlink/@w:anchor',namespaces=ns)
  self.assertTrue(refs);self.assertTrue(set(refs)<=set(bookmarks));self.assertEqual(len(bookmarks),len(set(bookmarks)))
 def test_global_numbers_ignore_completion_order_and_table_ids_are_local(self):
  first,_=self.decode([self.table()]);second=copy.deepcopy(first)
  for s in second:s['node_id']='other-'+s['node_id']
  numbers={}
  for sections in [second,first]:
   for s in sections:
    for block in s['blocks']:obj.register(numbers,block,s['node_id'])
  a=c.render_sections(first,self.fx.bundle['resources'],self.fx.project,numbers)
  b2=c.render_sections(second,self.fx.bundle['resources'],self.fx.project,numbers)
  self.assertEqual(a[1]['displayBlocks'][0]['label'],'表 2');self.assertEqual(b2[1]['displayBlocks'][0]['label'],'表 1')
 def test_old_v2_is_readable_without_guessing_number_replacements(self):
  self.fx.bundle['schemaVersion']='review-unit-resource-blocks-v2'
  sections,errors=self.decode([{'type':'markdown','text':'见图9 [E1]。'},{'type':'resource','resource_id':'R2'}]);self.assertFalse(errors)
  rendered=c.render_sections(sections,self.fx.bundle['resources'],self.fx.project)[1]
  self.assertEqual(rendered['displayBlocks'][0]['type'],'notice');self.assertIn('见图9',rendered['markdown'])
  self.assertEqual(rendered['displayBlocks'][-1]['label'],'图 1')
 def test_redundant_object_prefixes_are_consumed_only_at_bound_refs(self):
  text='见表 {{ref:T1}}、图{{ref:R2}}；示意图 {{ref:R2}}；Table {{ref:T1}}；Figure {{ref:R2}}。'
  sections,errors=self.decode([{'type':'markdown','text':text},self.table(),{'type':'resource','resource_id':'R2'}])
  self.assertFalse(errors)
  rendered=c.render_sections(sections,self.fx.bundle['resources'],self.fx.project)
  body=rendered[1]['displayBlocks'][0]['text']
  self.assertIn('见[表 1]',body);self.assertIn('、[图 1]',body);self.assertIn('示意[图 1]',body)
  self.assertNotIn('Table [表',body);self.assertNotIn('Figure [图',body)
  self.assertEqual(sections[1]['sourceBlocks'][0]['text'],text)
 def test_bare_evidence_ranges_resolve_and_keep_all_bindings(self):
  table=self.table();table['notes']='证据来自 E1–E2。E2为摘要；PGE2、APOE4 是分子名。'
  sections,errors=self.decode([table]);self.assertFalse(errors)
  self.assertEqual(sections[1]['blocks'][0]['notes'],'证据来自 (PMID: 12345678, 23456789)。(PMID: 23456789)为摘要；PGE2、APOE4 是分子名。')
  self.assertEqual(sections[1]['sourceBlocks'][0]['notes'],table['notes'])
  self.assertEqual({r['id'] for r in sections[1]['citationRefs']},{'E1','E2','R1'})
  for note in ['E999为摘要','E1–E999','E2–E1']:
   table['notes']=note;self.assertIn('a',self.decode([table])[1])
  # Existing saved output can be repaired for display using the complete frozen pool,
  # even when the old citationRefs omitted the bare ID.
  sections[1]['blocks'][0]['notes']='E2为摘要';sections[1]['citationRefs']=[r for r in sections[1]['citationRefs'] if r['id']!='E2']
  before=copy.deepcopy(sections)
  rendered=c.render_sections(sections,self.fx.bundle['resources'],self.fx.project,evidence=self.fx.bundle['evidencePool'])
  self.assertEqual(rendered[1]['displayBlocks'][0]['notes'],'(PMID: 23456789)为摘要');self.assertEqual(sections,before)
 def test_source_links_become_text_and_object_external_links_survive(self):
  from bs4 import BeautifulSoup
  from text_presentation import strip_source_links
  text=r'Source [\[1\]](#page-2-0), [Fig. 2](#page-5-1); [object](#obj_valid); [external](https://example.org/#page-2-0).'
  plain=strip_source_links(text)
  self.assertNotIn('](#page-',plain);self.assertIn(r'\[1\]',plain)
  soup=x.markdown_html(text)
  self.assertFalse(soup.select('a[href^="#page-"]'));self.assertIn('Fig. 2',soup.get_text())
  self.assertEqual({a['href'] for a in soup.find_all('a')},{'#obj_valid','https://example.org/#page-2-0'})
  self.fx.bundle['resources'][0]['content']='| A | B |\n|---|---|\n| source | [42](#page-2-0) |'
  self.fx.bundle['resources'][0]['context'][0]['text']=text
  sections,errors=self.decode([{'type':'resource','resource_id':'R1'}]);self.assertFalse(errors)
  rendered=c.render_sections(sections,self.fx.bundle['resources'],self.fx.project)[1]
  self.assertNotIn('](#page-',rendered['markdown'])
  self.assertFalse(x.blocks_html(rendered['displayBlocks']).select('a[href^="#page-"]'))

if __name__=='__main__':unittest.main()
