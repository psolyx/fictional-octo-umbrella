from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from .sqlite_backend import SQLiteBackend


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Session:
    user_id: str
    device_id: str
    session_token: str
    resume_token: str
    expires_at_ms: int


class SQLiteSessionStore:
    """Durable session store backed by SQLite."""

    def __init__(self, backend: SQLiteBackend, ttl_ms: int = 60 * 60 * 1000) -> None:
        self._backend = backend
        self._ttl_ms = ttl_ms

    def create(self, user_id: str, device_id: str) -> Session:
        session = Session(
            user_id=user_id,
            device_id=device_id,
            session_token=f"st_{secrets.token_urlsafe(16)}",
            resume_token=f"rt_{secrets.token_urlsafe(16)}",
            expires_at_ms=_now_ms() + self._ttl_ms,
        )
        with self._backend.lock:
            self._backend.connection.execute(
                """
                INSERT INTO sessions (session_token, resume_token, device_id, user_id, expires_at_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.session_token,
                    session.resume_token,
                    session.device_id,
                    session.user_id,
                    session.expires_at_ms,
                ),
            )
        return session

    def get_by_session(self, session_token: str) -> Session | None:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT session_token, resume_token, device_id, user_id, expires_at_ms FROM sessions WHERE session_token=?",
                (session_token,),
            ).fetchone()
        if row is None:
            return None
        session = Session(
            session_token=row[0],
            resume_token=row[1],
            device_id=row[2],
            user_id=row[3],
            expires_at_ms=row[4],
        )
        if session.expires_at_ms <= _now_ms():
            self.invalidate(session)
            return None
        return session

    def get_by_resume(self, resume_token: str) -> Session | None:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT session_token, resume_token, device_id, user_id, expires_at_ms FROM sessions WHERE resume_token=?",
                (resume_token,),
            ).fetchone()

        if row is None:
            return None

        session = Session(
            session_token=row[0],
            resume_token=row[1],
            device_id=row[2],
            user_id=row[3],
            expires_at_ms=row[4],
        )
        if session.expires_at_ms <= _now_ms():
            self.invalidate(session)
            return None
        return session

    def consume_resume(self, resume_token: str) -> Session | None:
        now_ms = _now_ms()
        new_resume_token = f"rt_{secrets.token_urlsafe(16)}"
        expires_at = now_ms + self._ttl_ms

        with self._backend.lock:
            conn = self._backend.connection
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT session_token, resume_token, device_id, user_id, expires_at_ms FROM sessions WHERE resume_token=?",
                (resume_token,),
            ).fetchone()

            if row is None:
                conn.commit()
                return None

            session = Session(
                session_token=row[0],
                resume_token=row[1],
                device_id=row[2],
                user_id=row[3],
                expires_at_ms=row[4],
            )
            if session.expires_at_ms <= now_ms:
                conn.execute("DELETE FROM sessions WHERE resume_token=?", (resume_token,))
                conn.commit()
                return None

            conn.execute(
                "UPDATE sessions SET resume_token=?, expires_at_ms=? WHERE resume_token=?",
                (new_resume_token, expires_at, resume_token),
            )
            conn.commit()

        session.resume_token = new_resume_token
        session.expires_at_ms = expires_at
        return session

    def rotate_resume(self, session: Session) -> Session:
        new_token = f"rt_{secrets.token_urlsafe(16)}"
        expires_at = _now_ms() + self._ttl_ms
        with self._backend.lock:
            self._backend.connection.execute(
                "UPDATE sessions SET resume_token=?, expires_at_ms=? WHERE session_token=?",
                (new_token, expires_at, session.session_token),
            )
        session.resume_token = new_token
        session.expires_at_ms = expires_at
        return session


    def list_for_user(self, user_id: str) -> list[Session]:
        now_ms = _now_ms()
        with self._backend.lock:
            conn = self._backend.connection
            conn.execute("DELETE FROM sessions WHERE user_id=? AND expires_at_ms<=?", (user_id, now_ms))
            rows = conn.execute(
                """
                SELECT session_token, resume_token, device_id, user_id, expires_at_ms
                FROM sessions
                WHERE user_id=?
                ORDER BY device_id ASC, session_token ASC
                """,
                (user_id,),
            ).fetchall()
        sessions: list[Session] = []
        for row in rows:
            sessions.append(
                Session(
                    session_token=row[0],
                    resume_token=row[1],
                    device_id=row[2],
                    user_id=row[3],
                    expires_at_ms=row[4],
                )
            )
        return sessions

    def invalidate_token(self, session_token: str) -> None:
        with self._backend.lock:
            self._backend.connection.execute(
                "DELETE FROM sessions WHERE session_token=?",
                (session_token,),
            )

    def invalidate_all_for_user(self, user_id: str, keep_session_token: str | None = None) -> int:
        with self._backend.lock:
            if keep_session_token is None:
                cursor = self._backend.connection.execute(
                    "DELETE FROM sessions WHERE user_id=?",
                    (user_id,),
                )
            else:
                cursor = self._backend.connection.execute(
                    "DELETE FROM sessions WHERE user_id=? AND session_token<>?",
                    (user_id, keep_session_token),
                )
        return int(cursor.rowcount)

    def invalidate(self, session: Session) -> None:
        with self._backend.lock:
            self._backend.connection.execute(
                "DELETE FROM sessions WHERE session_token=?",
                (session.session_token,),
            )
