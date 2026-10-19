import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from file_identity import change_ns
import storage


class FileIdentityTests(unittest.TestCase):
    def test_edit_with_restored_mtime_changes_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'paper.md';path.write_bytes(b'old')
            before=path.stat();identity=change_ns(path,before)
            # Windows may coalesce metadata timestamps within a system clock tick.
            time.sleep(.03)
            path.write_bytes(b'new');os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
            self.assertNotEqual(change_ns(path),identity)

    def test_independent_shared_reader_and_exclusive_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'storage.lock'
            script=('import sys;sys.path.insert(0,sys.argv[1]);import storage;'
                    'from pathlib import Path;'
                    '\nwith storage.file_lock(Path(sys.argv[2]),shared=sys.argv[3]=="read"):print("locked")')
            def child(mode):
                return subprocess.run([sys.executable,'-c',script,str(Path(storage.__file__).parent),str(path),mode],
                                      capture_output=True,text=True,timeout=10)
            with storage.file_lock(path,shared=True):
                self.assertEqual(child('read').returncode,0)
                self.assertNotEqual(child('write').returncode,0)
            self.assertEqual(child('write').returncode,0)
