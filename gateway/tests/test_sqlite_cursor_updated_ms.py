import os
import sqlite3
import tempfile
import unittest

from gateway.sqlite_backend import SQLiteBackend
from gateway.sqlite_cursors import SQLiteCursorStore


class SQLiteCursorUpdatedMsTests(unittest.TestCase):
    def test_v7_to_v8_migration_adds_updated_ms_and_preserves_next_seq(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "gateway.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE cursors (
                    device_id TEXT NOT NULL,
                    conv_id TEXT NOT NULL,
                    next_seq INTEGER NOT NULL,
                    PRIMARY KEY (device_id, conv_id)
                )
                """
            )
            conn.execute(
                "INSERT INTO cursors (device_id, conv_id, next_seq) VALUES (?, ?, ?)",
                ("d1", "c1", 7),
            )
            conn.execute("PRAGMA user_version = 7")
            conn.commit()
            conn.close()

            backend = SQLiteBackend(db_path)
            row = backend.connection.execute(
                "SELECT next_seq, updated_ms FROM cursors WHERE device_id=? AND conv_id=?",
                ("d1", "c1"),
            ).fetchone()
            self.assertEqual(int(row[0]), 7)
            self.assertEqual(int(row[1]), 0)
            backend.close()

    def test_ack_updates_updated_ms_and_active_min_next_seq(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = SQLiteBackend(os.path.join(tmpdir, "gateway.db"))
            store = SQLiteCursorStore(backend)

            store.ack("d1", "c1", 9)
            store.ack("d2", "c1", 2)

            rows = backend.connection.execute(
                "SELECT updated_ms FROM cursors WHERE conv_id=? ORDER BY device_id ASC",
                ("c1",),
            ).fetchall()
            self.assertGreater(int(rows[0][0]), 0)
            self.assertGreater(int(rows[1][0]), 0)

            newest = max(int(rows[0][0]), int(rows[1][0]))
            min_next = store.active_min_next_seq("c1", now_ms=newest + 1, cursor_stale_after_ms=0)
            self.assertEqual(min_next, 3)

            stale_cutoff = 1
            active_with_window = store.active_min_next_seq(
                "c1", now_ms=newest + stale_cutoff + 1, cursor_stale_after_ms=stale_cutoff
            )
            self.assertIsNone(active_with_window)
            backend.close()


if __name__ == "__main__":
    unittest.main()
