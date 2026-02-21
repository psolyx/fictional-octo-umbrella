from __future__ import annotations

from .sqlite_backend import SQLiteBackend
from .sqlite_sessions import _now_ms


class SQLiteCursorStore:
    """Durable cursor store backed by SQLite."""

    def __init__(self, backend: SQLiteBackend) -> None:
        self._backend = backend

    def ack(self, device_id: str, conv_id: str, acked_seq: int) -> int:
        if acked_seq < 0:
            raise ValueError("acked_seq must be non-negative")

        next_seq = max(1, acked_seq + 1)
        updated_ms = _now_ms()
        with self._backend.lock:
            self._backend.connection.execute(
                """
                INSERT INTO cursors (device_id, conv_id, next_seq, updated_ms)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id, conv_id) DO UPDATE SET
                    next_seq = CASE
                    WHEN excluded.next_seq > cursors.next_seq THEN excluded.next_seq
                    ELSE cursors.next_seq
                END,
                    updated_ms = excluded.updated_ms
                """,
                (device_id, conv_id, next_seq, updated_ms),
            )
            row = self._backend.connection.execute(
                "SELECT next_seq FROM cursors WHERE device_id=? AND conv_id=?",
                (device_id, conv_id),
            ).fetchone()
        return int(row[0]) if row else next_seq

    def active_min_next_seq(self, conv_id: str, now_ms: int, cursor_stale_after_ms: int) -> int | None:
        with self._backend.lock:
            if cursor_stale_after_ms <= 0:
                row = self._backend.connection.execute(
                    "SELECT MIN(next_seq) FROM cursors WHERE conv_id=?",
                    (conv_id,),
                ).fetchone()
            else:
                stale_cutoff_ms = now_ms - cursor_stale_after_ms
                row = self._backend.connection.execute(
                    "SELECT MIN(next_seq) FROM cursors WHERE conv_id=? AND updated_ms>=?",
                    (conv_id, stale_cutoff_ms),
                ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def next_seq(self, device_id: str, conv_id: str) -> int:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT next_seq FROM cursors WHERE device_id=? AND conv_id=?",
                (device_id, conv_id),
            ).fetchone()
        return int(row[0]) if row else 1

    def last_ack(self, device_id: str, conv_id: str) -> int:
        return self.next_seq(device_id, conv_id) - 1

    def list_cursors(self, device_id: str) -> list[tuple[str, int]]:
        with self._backend.lock:
            rows = self._backend.connection.execute(
                "SELECT conv_id, next_seq FROM cursors WHERE device_id=? ORDER BY conv_id ASC",
                (device_id,),
            ).fetchall()
        return [(row[0], int(row[1])) for row in rows]
