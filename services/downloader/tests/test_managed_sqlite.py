from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import managed_sqlite
import sqlite3


class ConnectionTests(unittest.TestCase):
    def test_commit_closes_handle_and_allows_directory_move(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); project=root/'project'; project.mkdir()
            with managed_sqlite.connect(project/'db.sqlite3') as db:
                db.execute('CREATE TABLE test(value)')
                db.execute('INSERT INTO test VALUES (1)')
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            moved=root/'moved'; project.rename(moved)
            with managed_sqlite.connect(moved/'db.sqlite3') as db:
                self.assertEqual(db.execute('SELECT value FROM test').fetchone(),(1,))

    def test_exception_rolls_back_and_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.sqlite3'
            with managed_sqlite.connect(path) as db:
                db.execute('CREATE TABLE test(value)')
            with self.assertRaisesRegex(ValueError,'fixture'):
                with managed_sqlite.connect(path) as db:
                    db.execute('INSERT INTO test VALUES (1)')
                    raise ValueError('fixture')
            with managed_sqlite.connect(path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM test').fetchone()[0],0)
