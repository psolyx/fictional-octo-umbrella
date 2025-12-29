import os
import os
import tempfile
import unittest

from gateway.sqlite_backend import SQLiteBackend
from gateway.sqlite_cursors import SQLiteCursorStore
from gateway.sqlite_log import SQLiteConversationLog
from gateway.sqlite_sessions import SQLiteSessionStore


class SQLiteBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "gateway.db")
        self.backend = SQLiteBackend(self.db_path)

    def tearDown(self) -> None:
        self.backend.close()
        self.tmpdir.cleanup()

    def test_append_and_idempotency(self):
        log = SQLiteConversationLog(self.backend)

        seq1, event1, created1 = log.append("c1", "m1", b"payload", "d1", 1)
        seq2, event2, created2 = log.append("c1", "m2", "ZW52", "d2", 2)
        seq3, event3, created3 = log.append("c1", "m1", b"ignored", "d3", 3)

        self.assertEqual((seq1, event1.seq, created1), (1, 1, True))
        self.assertEqual((seq2, event2.seq, created2), (2, 2, True))
        self.assertEqual((seq3, event3.seq, created3), (1, 1, False))

        events = log.list_from("c1", 1)
        self.assertEqual([e.seq for e in events], [1, 2])

    def test_cursors_and_sessions_survive_restart(self):
        cursors = SQLiteCursorStore(self.backend)
        sessions = SQLiteSessionStore(self.backend, ttl_ms=60_000)

        next_seq = cursors.ack("d1", "c1", 0)
        self.assertEqual(next_seq, 1)
        advanced = cursors.ack("d1", "c1", 5)
        self.assertEqual(advanced, 6)

        created_session = sessions.create("u1", "d1")
        loaded = sessions.get_by_resume(created_session.resume_token)
        self.assertIsNotNone(loaded)
        rotated = sessions.rotate_resume(loaded)
        resumed = sessions.get_by_resume(rotated.resume_token)

        self.assertIsNotNone(resumed)
        self.assertEqual(resumed.device_id, "d1")
        self.assertEqual(resumed.session_token, created_session.session_token)
        self.assertEqual(resumed.user_id, "u1")
