import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import html_compaction as c
import review_export as export
import project_compaction
import engine as e
import test_review_manuscripts as fixture


class HTMLCompactionTests(unittest.TestCase):
    def source(self):
        image='data:image/png;base64,'+base64.b64encode(b''.join(hashlib.sha256(str(i).encode()).digest() for i in range(300))).decode()
        resource={'id':'figure','kind':'figure','pmid':'123','lineStart':1,'lineEnd':3,
                  'dataUrl':image,'context':[{'position':'before','html':'<p>Shared context</p>'}]}
        entry={'id':'chunk','html':'<p>Shared evidence</p>','resources':[resource]}
        refs={'1':{'123':[entry,'legacy <sup>2</sup>']},'2':{'123':[entry]}}
        refs['3']={'123':[{'id':'chunk','html':'<p>Different evidence, same ID</p>','resources':[{**resource,'lineStart':9}]}]}
        blocks={str(n):[{'type':'markdown','text':f'Claim {n} (PMID: 123)'},
                       {'type':'resource','kind':'figure','resourceId':'figure','label':'图 1','pmid':'123','dataUrl':image}]
                for n in range(1,4)}
        rows=[{'serial':str(n),'title':'Section '+str(n)} for n in range(1,4)]
        with patch.object(c,'compact_html',side_effect=lambda text:text):
            source=export.html_document('Title',rows,{str(n):f'Claim {n} (PMID: 123)' for n in range(1,4)},refs,False,blocks)
        return source,refs,image

    def test_images_and_evidence_shared_but_scope_and_body_are_exact(self):
        source,refs,image=self.source();result=c.compact_html(source)
        old_prefix,_,_,old_suffix=c.parts(source);prefix,data,_,suffix=c.parts(result)
        self.assertLess(len(result),len(source)*.65)
        self.assertEqual(len(data['images']),1);self.assertEqual(result.count(image),1)
        self.assertEqual(len(data['resources']),2)  # Same image, distinct source positions.
        self.assertEqual(len(data['entries']),3)  # Includes the legacy string.
        self.assertEqual(data['scopes']['1']['123'][0],data['scopes']['2']['123'][0])
        self.assertNotEqual(data['scopes']['2']['123'][0],data['scopes']['3']['123'][0])
        self.assertEqual(c.unpack(data),refs)
        self.assertEqual(c.expand_body(prefix,data),old_prefix);self.assertEqual(suffix,old_suffix)
        self.assertEqual(c.compact_html(result),result)

    def test_pool_integrity_and_missing_images_reject_migration(self):
        source,_,_=self.source();result=c.compact_html(source);prefix,data,reader,suffix=c.parts(result)
        key=next(iter(data['images']));data['images'][key]+='x'
        broken=prefix+c.MARKER+c.encoded(data)+'</script><script>'+reader+'</script>'+suffix
        with self.assertRaisesRegex(ValueError,'校验'):c.compact_html(broken)

    def test_custom_or_prototype_reader_is_not_replaced(self):
        source,_,_=self.source();prefix,refs,_,suffix=c.parts(source)
        custom=prefix+c.MARKER+json.dumps(refs)+'</script><script>customReader()</script>'+suffix
        with self.assertRaises(c.UnsupportedHTML):c.compact_html(custom)
        with self.assertRaises(c.UnsupportedHTML):c.compact_html('<html>unrelated file</html>')

    def test_source_markup_remains_escaped_and_no_external_resource_paths(self):
        rows=[{'serial':'1','title':'Title'}]
        refs={'1':{'123':['</script><script>bad()</script>']}}
        result=export.html_document('Title',rows,{'1':'Claim (PMID: 123)'},refs,False)
        self.assertNotIn('<script>bad()</script>',result)
        self.assertEqual(c.unpack(c.parts(result)[1]),refs)
        self.assertNotIn('fetch(',result)


class HTMLMigrationTests(unittest.TestCase):
    setUp=fixture.ManuscriptTests.setUp
    tearDown=fixture.ManuscriptTests.tearDown

    def test_opt_in_atomic_migration_and_idempotence(self):
        source,refs,_=HTMLCompactionTests().source()
        path=self.path/'exports/saved.html';e.atomic(path,source)
        unrelated=self.path/'exports/custom.html';e.atomic(unrelated,'<html>Custom</html>')
        self.assertEqual(project_compaction.compact_project(e,True)['htmlFiles'],0)
        before=path.read_bytes();estimate=project_compaction.compact_project(e,include_html=True)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(estimate['htmlFiles'],1)
        with patch.object(e,'atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):project_compaction.compact_project(e,True,True)
        self.assertEqual(path.read_bytes(),before)
        report=project_compaction.compact_project(e,True,True)
        self.assertEqual(c.unpack(c.parts(path.read_text())[1]),refs)
        self.assertEqual(len(before)-path.stat().st_size,report['savedBytes'])
        self.assertEqual(unrelated.read_text(),'<html>Custom</html>')
        self.assertEqual(project_compaction.compact_project(e,True,True)['savedBytes'],0)


if __name__=='__main__':unittest.main()
