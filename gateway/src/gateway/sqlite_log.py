from __future__ import annotations

import base64

import sqlite3

from .log import ConversationEvent
from .sqlite_backend import SQLiteBackend


class SQLiteConversationLog:
    """Durable conversation log backed by SQLite."""

    def __init__(self, backend: SQLiteBackend) -> None:
        self._backend = backend

    def append(
        self,
        conv_id: str,
        msg_id: str,
        envelope_bytes_or_b64: bytes | str,
        sender_device_id: str,
        ts_ms: int,
    ) -> tuple[int, ConversationEvent, bool]:
        """Append an event atomically and enforce idempotency."""

        envelope_b64 = self._to_b64(envelope_bytes_or_b64)
        conn = self._backend.connection
        with self._backend.lock:
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                row = cursor.execute(
                    "SELECT seq, env_b64, sender_device_id, ts_ms FROM conv_events WHERE conv_id=? AND msg_id=?",
                    (conv_id, msg_id),
                ).fetchone()
                if row:
                    conn.commit()
                    event = ConversationEvent(
                        conv_id=conv_id,
                        seq=row[0],
                        msg_id=msg_id,
                        envelope_b64=row[1],
                        sender_device_id=row[2],
                        ts_ms=row[3],
                    )
                    return row[0], event, False

                cursor.execute("INSERT OR IGNORE INTO conv_seq (conv_id, next_seq) VALUES (?, 1)", (conv_id,))
                seq_row = cursor.execute("SELECT next_seq FROM conv_seq WHERE conv_id=?", (conv_id,)).fetchone()
                seq = int(seq_row[0])
                cursor.execute("UPDATE conv_seq SET next_seq = next_seq + 1 WHERE conv_id=?", (conv_id,))
                cursor.execute(
                    """
                    INSERT INTO conv_events (conv_id, seq, msg_id, env_b64, sender_device_id, ts_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (conv_id, seq, msg_id, envelope_b64, sender_device_id, ts_ms),
                )
                conn.commit()
                event = ConversationEvent(
                    conv_id=conv_id,
                    seq=seq,
                    msg_id=msg_id,
                    envelope_b64=envelope_b64,
                    sender_device_id=sender_device_id,
                    ts_ms=ts_ms,
                )
                return seq, event, True
            except sqlite3.IntegrityError:
                conn.rollback()
                existing = conn.execute(
                    "SELECT seq, env_b64, sender_device_id, ts_ms FROM conv_events WHERE conv_id=? AND msg_id=?",
                    (conv_id, msg_id),
                ).fetchone()
                if existing:
                    event = ConversationEvent(
                        conv_id=conv_id,
                        seq=existing[0],
                        msg_id=msg_id,
                        envelope_b64=existing[1],
                        sender_device_id=existing[2],
                        ts_ms=existing[3],
                    )
                    return existing[0], event, False
                raise
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def list_since(self, conv_id: str, after_seq: int, limit: int | None = None) -> list[ConversationEvent]:
        if after_seq < 0:
            raise ValueError("after_seq must be non-negative")
        return self.list_from(conv_id, after_seq + 1, limit)

    def list_from(self, conv_id: str, from_seq: int, limit: int | None = None) -> list[ConversationEvent]:
        if from_seq < 1:
            raise ValueError("from_seq must be at least 1")

        query = "SELECT conv_id, seq, msg_id, env_b64, sender_device_id, ts_ms FROM conv_events WHERE conv_id=? AND seq>=? ORDER BY seq ASC"
        params: list[object] = [conv_id, from_seq]
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(limit, 0))

        with self._backend.lock:
            rows = self._backend.connection.execute(query, params).fetchall()

        return [
            ConversationEvent(
                conv_id=row[0],
                seq=row[1],
                msg_id=row[2],
                envelope_b64=row[3],
                sender_device_id=row[4],
                ts_ms=row[5],
            )
            for row in rows
        ]

    @staticmethod
    def _to_b64(envelope_bytes_or_b64: bytes | str) -> str:
        if isinstance(envelope_bytes_or_b64, bytes):
            return base64.b64encode(envelope_bytes_or_b64).decode("ascii")
        return envelope_bytes_or_b64
