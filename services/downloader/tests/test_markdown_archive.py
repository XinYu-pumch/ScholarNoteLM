import hashlib,json,unittest
from unittest.mock import patch
import test_artifact_state as fixture
import engine as e,corpus_files as f,markdown_archive as archive,library_service as library,markdown_service as m,artifact_state as a

class MarkdownArchiveTests(unittest.TestCase):
 setUp=fixture.ArtifactStateTests.setUp
 tearDown=fixture.ArtifactStateTests.tearDown
 xml=fixture.ArtifactStateTests.xml
 materialize=fixture.ArtifactStateTests.materialize
 def remove(self):self.xml(['2']);return f.reconcile(e)
 def restore(self):self.xml(['1','2']);return f.reconcile(e)
 def test_complete_bundle_restored_with_new_epoch_and_no_repeat_writes(self):
  self.materialize('1');e.atomic(self.base/'markdown/1.md','User edited clean text')
  originals={'markdown/assets/1/p.png':b'image','markdown/history/1/old.md':b'previous'}
  for name,content in originals.items():e.atomic(self.base/name,content)
  self.assertEqual(self.remove()['archivedMarkdown'],1);self.assertEqual(self.restore()['restoredMarkdown'],1)
  for name,content in originals.items():self.assertEqual((self.base/name).read_bytes(),content)
  self.assertEqual((self.base/'markdown/1.md').read_text(),'User edited clean text')
  self.assertEqual(json.loads((self.base/'metadata/markdown/1.json').read_text())['rebuildEpoch'],a.epoch(e,'1'))
  before={p:p.stat().st_mtime_ns for p in self.base.rglob('*') if p.is_file()}
  f.reconcile(e);self.assertEqual(before,{p:p.stat().st_mtime_ns for p in self.base.rglob('*') if p.is_file()})
  self.remove();self.restore();self.assertEqual(len(list((self.base/'archive/markdown/1').glob('*/manifest.json'))),1)
 def test_pdf_or_conversion_change_rejects_backup(self):
  self.materialize('1');self.remove()
  pdf=self.base/'pdf/redundant/1.pdf';pdf.write_bytes(pdf.read_bytes().replace(b'100',b'101'))
  self.assertEqual(self.restore()['restoredMarkdown'],0)
  self.assertFalse((self.base/'markdown/1.md').exists())
 def test_incompatible_cleaning_or_engine_rejects_backup(self):
  self.materialize('1');self.remove()
  with patch.object(m,'signature',return_value='different'):self.assertEqual(self.restore()['restoredMarkdown'],0)
  with patch('conversion_config.matches',return_value=False):self.assertFalse(archive.restore(e,'1'))
 def test_corrupt_bundle_and_existing_conflicts_are_not_overwritten(self):
  self.materialize('1');self.remove();folder=next((self.base/'archive/markdown/1').iterdir())
  (folder/'markdown/1.md').write_text('corrupt');self.assertEqual(self.restore()['restoredMarkdown'],0)
  self.materialize('1');self.assertEqual(self.remove()['archivedMarkdown'],1)
  self.assertEqual(len(list((self.base/'archive/markdown/1').glob('*/manifest.json'))),2)
  self.assertEqual(self.restore()['restoredMarkdown'],1)
  (self.base/'metadata/markdown/1.json').unlink();e.atomic(self.base/'markdown/1.md','current edit')
  self.assertFalse(archive.restore(e,'1'));self.assertEqual((self.base/'markdown/1.md').read_text(),'current edit')
 def test_invalid_or_missing_provenance_still_preserved_without_restoring(self):
  self.materialize('1');e.atomic(self.base/'metadata/markdown/1.json','broken json');e.atomic(self.base/'pdf/1.pdf',b'bad pdf')
  self.assertEqual(self.remove()['archivedMarkdown'],1)
  manifest=json.loads(next((self.base/'archive/markdown/1').glob('*/manifest.json')).read_text())
  self.assertFalse(manifest['restorable']);self.assertIn('markdown/raw/1.md',manifest['files'])
 def test_explicit_clear_cannot_resurrect_old_markdown(self):
  self.materialize('1');self.remove();self.restore()
  with patch.object(library,'running',return_value=[]):library.clear_idle(e,{'scope':'markdown','includeRedundant':False})
  self.assertEqual(f.reconcile(e)['restoredMarkdown'],0);self.remove();self.restore()
  self.assertFalse((self.base/'markdown/1.md').exists())
  # A new conversion can be archived and restored after explicit clearing.
  self.materialize('1');self.remove();self.assertEqual(self.restore()['restoredMarkdown'],1)
 def test_stale_epoch_cannot_be_laundered_by_restore(self):
  self.materialize('1');meta=self.base/'metadata/markdown/1.json';data=json.loads(meta.read_text());data['rebuildEpoch']=-1;e.write_json(meta,data)
  self.remove();self.assertEqual(self.restore()['restoredMarkdown'],0)

 def test_clear_current_markdown_keeps_excluded_backup_eligible(self):
  self.materialize('1');self.remove()
  with patch.object(library,'running',return_value=[]):library.clear_idle(e,{'scope':'markdown','includeRedundant':False})
  self.assertEqual(self.restore()['restoredMarkdown'],1)
