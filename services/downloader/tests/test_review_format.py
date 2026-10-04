import json,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import review_format as f,review_export as x
class FormatTests(unittest.TestCase):
 def setUp(self):
  self.nodes=[{'id':'a'*32,'serial':'1','title':'机制'},{'id':'b'*32,'serial':'1.1','title':'肠道菌群'},{'id':'c'*32,'serial':'1.2','title':'免疫调节'}]
  self.unit={**self.nodes[0],'nodes':self.nodes,'leaves':self.nodes[1:],'ancestors':[],'siblings':[]}
  self.evidence={n['id']:{'query':n['title'],'chunks':[{'id':'debug-id','text':n['title']+' evidence','metadata':{'pmid':'12345678','sourceKind':'fulltext','title':'Not in prompt','secretMeta':'omit'}}]} for n in self.nodes[1:]}
  self.snapshot={'topic':'研究主题','config':{'language':'中文','requirements':'谨慎措辞'}}
 def test_public_json_round_trip_and_scopes(self):
  internal=[{'node_id':n['id'],'title':n['title'],'markdown':'正文'} for n in self.nodes];out=f.public_part(self.unit,internal,self.evidence)
  self.assertEqual(set(out),{'unit_id','sections','citation_validation','citation_scopes','reference_materials','markdown_content'})
  self.assertEqual(out['citation_scopes']['1'],[]);self.assertEqual(out['reference_materials']['1.1']['12345678'],['肠道菌群 evidence']);self.assertNotIn('a'*32,json.dumps(out))
  self.assertIn('## 1.2 免疫调节',out['markdown_content'])
 def test_html_markdown_and_script_escape(self):
  text='**加粗**，*斜体* (PMID: 12345678)。\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1))'
  html=x.html_document('Title',self.nodes,{'1.1':text},{'1.1':{'12345678':['</script><script>bad</script>']}},False)
  self.assertIn('<strong>加粗</strong>',html);self.assertIn('<em>斜体</em>',html);self.assertNotIn('href="javascript:',html);self.assertNotIn('</script><script>bad</script>',html)
  self.assertIn('data-scope="1.1"',html);self.assertIn('data-pmid="12345678"',html)
 def test_word_headings_bold_lists_and_pmid_links(self):
  import xml.etree.ElementTree as ET
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]/'tmp') as tmp:
   p=Path(tmp)/'test.docx';x.word_document(p,'Title',self.nodes,{'1.1':'**粗体**与*斜体* (PMID: 12345678)\n\n- 一\n- 二'},False)
   with zipfile.ZipFile(p) as z:
    xml=z.read('word/document.xml').decode();ET.fromstring(xml)
    self.assertIn('Heading2',xml);self.assertIn('ListBullet',xml);self.assertIn('<w:b',xml);self.assertIn('<w:i',xml)
    self.assertIn('https://pubmed.ncbi.nlm.nih.gov/12345678/',z.read('word/_rels/document.xml.rels').decode())
if __name__=='__main__':unittest.main()
