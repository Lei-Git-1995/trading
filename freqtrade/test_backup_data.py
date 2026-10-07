"""Offline checks for consistent SQLite backup."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backup_data import backup_sqlite


class BackupTests(unittest.TestCase):
    def test_sqlite_backup_is_independent_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.sqlite"
            target = Path(temp) / "target.sqlite"
            db = sqlite3.connect(source)
            try:
                db.execute("CREATE TABLE sample (value INTEGER)")
                db.execute("INSERT INTO sample VALUES (7)")
                db.commit()
                backup_sqlite(source, target)
                db.execute("INSERT INTO sample VALUES (8)")
                db.commit()
            finally:
                db.close()
            snap = sqlite3.connect(target)
            try:
                self.assertEqual(snap.execute("SELECT value FROM sample").fetchall(), [(7,)])
            finally:
                snap.close()


if __name__ == "__main__":
    unittest.main()
