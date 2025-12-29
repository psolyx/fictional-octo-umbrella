from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class SQLiteBackend:
    """Owns a shared SQLite connection and applies gateway migrations."""

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._apply_migrations()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    def close(self) -> None:
        self._conn.close()

    def _configure(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def _apply_migrations(self) -> None:
        user_version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if user_version == 0:
            legacy_version = self._read_legacy_schema_version()
            if legacy_version is None:
                self._create_v1_schema()
                self._conn.execute("PRAGMA user_version = 1")
            elif legacy_version == 1:
                self._conn.execute("PRAGMA user_version = 1")
            else:
                raise ValueError(f"Unsupported schema version: {legacy_version}")
        elif user_version != 1:
            raise ValueError(f"Unsupported schema version: {user_version}")

    def _read_legacy_schema_version(self) -> int | None:
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        if row is None:
            return None
        version_row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if version_row is None:
            return None
        return int(version_row[0])

    def _create_v1_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conv_events (
                conv_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                msg_id TEXT NOT NULL,
                env_b64 TEXT NOT NULL,
                sender_device_id TEXT NOT NULL,
                ts_ms INTEGER NOT NULL,
                PRIMARY KEY (conv_id, seq),
                UNIQUE (conv_id, msg_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conv_seq (
                conv_id TEXT PRIMARY KEY,
                next_seq INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cursors (
                device_id TEXT NOT NULL,
                conv_id TEXT NOT NULL,
                next_seq INTEGER NOT NULL,
                PRIMARY KEY (device_id, conv_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_token TEXT PRIMARY KEY,
                resume_token TEXT NOT NULL UNIQUE,
                device_id TEXT NOT NULL,
                expires_at_ms INTEGER NOT NULL
            )
            """
        )
