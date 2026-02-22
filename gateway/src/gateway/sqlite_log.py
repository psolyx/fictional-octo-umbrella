from __future__ import annotations

import base64
import sqlite3

from .log import ConversationEvent
from .retention import ReplayWindowExceeded, RetentionPolicy
from .sqlite_backend import SQLiteBackend


class SQLiteConversationLog:
    """Durable conversation log backed by SQLite."""

    def __init__(self, backend: SQLiteBackend, retention_policy: RetentionPolicy | None = None) -> None:
        self._backend = backend
        self._retention_policy = retention_policy

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

        earliest_seq = self.earliest_seq(conv_id)
        if self._retention_policy is not None and self._retention_policy.enabled and earliest_seq is not None and from_seq < earliest_seq:
            latest_seq = self.latest_seq(conv_id) or earliest_seq
            raise ReplayWindowExceeded(
                conv_id=conv_id,
                requested_from_seq=from_seq,
                earliest_seq=earliest_seq,
                latest_seq=latest_seq,
            )

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

    def bounds(self, conv_id: str) -> tuple[int | None, int | None, int | None]:
        with self._backend.lock:
            row = self._backend.connection.execute(
                """
                SELECT
                    MIN(seq) AS earliest_seq,
                    MAX(seq) AS latest_seq,
                    (
                        SELECT ts_ms
                        FROM conv_events
                        WHERE conv_id=?
                        ORDER BY seq DESC
                        LIMIT 1
                    ) AS latest_ts_ms
                FROM conv_events
                WHERE conv_id=?
                """,
                (conv_id, conv_id),
            ).fetchone()
        if row is None or row[0] is None or row[1] is None:
            return None, None, None
        latest_ts_ms = int(row[2]) if row[2] is not None else None
        return int(row[0]), int(row[1]), latest_ts_ms

    def earliest_seq(self, conv_id: str) -> int | None:
        earliest_seq, _, _ = self.bounds(conv_id)
        return earliest_seq

    def latest_seq(self, conv_id: str) -> int | None:
        _, latest_seq, _ = self.bounds(conv_id)
        return latest_seq

    def latest_ts_ms(self, conv_id: str) -> int | None:
        _, _, latest_ts_ms = self.bounds(conv_id)
        return latest_ts_ms

    def list_conversations(self) -> list[str]:
        with self._backend.lock:
            rows = self._backend.connection.execute(
                "SELECT DISTINCT conv_id FROM conv_events ORDER BY conv_id ASC"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def prune_conv(
        self,
        conv_id: str,
        policy: RetentionPolicy,
        now_ms: int,
        active_min_next_seq: int | None,
    ) -> int:
        if not policy.enabled:
            return 0

        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT MIN(seq), MAX(seq) FROM conv_events WHERE conv_id=?",
                (conv_id,),
            ).fetchone()
            if row is None or row[0] is None or row[1] is None:
                return 0
            min_seq = int(row[0])
            max_seq = int(row[1])

            cap_before_seq: int | None = None
            if policy.max_events_per_conv > 0:
                cap_before_seq = max_seq - policy.max_events_per_conv + 1

            age_cutoff_ms = now_ms - policy.max_age_ms if policy.max_age_s > 0 else None
            age_row = None
            if age_cutoff_ms is not None:
                age_row = self._backend.connection.execute(
                    "SELECT MAX(seq) FROM conv_events WHERE conv_id=? AND ts_ms<?",
                    (conv_id, age_cutoff_ms),
                ).fetchone()

            delete_upto_seq: int | None = None
            if cap_before_seq is not None:
                delete_upto_seq = cap_before_seq - 1

            if age_row is not None and age_row[0] is not None:
                age_delete_upto = int(age_row[0])
                delete_upto_seq = age_delete_upto if delete_upto_seq is None else max(delete_upto_seq, age_delete_upto)

            if delete_upto_seq is None:
                return 0

            delete_upto_seq = max(delete_upto_seq, min_seq - 1)
            if not policy.hard_limits and active_min_next_seq is not None:
                delete_upto_seq = min(delete_upto_seq, active_min_next_seq - 1)

            if delete_upto_seq < min_seq:
                return 0

            cursor = self._backend.connection.execute(
                "DELETE FROM conv_events WHERE conv_id=? AND seq<=?",
                (conv_id, delete_upto_seq),
            )
            return cursor.rowcount

    @staticmethod
    def _to_b64(envelope_bytes_or_b64: bytes | str) -> str:
        if isinstance(envelope_bytes_or_b64, bytes):
            return base64.b64encode(envelope_bytes_or_b64).decode("ascii")
        return envelope_bytes_or_b64
