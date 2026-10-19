"""Short-lived SQLite connections close after committing/rolling back a with block.

sqlite3.Connection.__exit__ only ends the transaction. Leaving handles to GC
prevents Windows from moving/deleting project folders and retains WAL handles.
Explicit users outside a with block still own the connection and must close it.
"""
import sqlite3


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(*args, **kwargs):
    kwargs.setdefault('factory', Connection)
    return sqlite3.connect(*args, **kwargs)
