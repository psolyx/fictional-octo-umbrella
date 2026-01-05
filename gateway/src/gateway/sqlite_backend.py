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
                user_version = 1
            elif legacy_version == 1:
                user_version = 1
            else:
                raise ValueError(f"Unsupported schema version: {legacy_version}")
        elif user_version not in (1, 2, 3, 4, 5, 6):
            raise ValueError(f"Unsupported schema version: {user_version}")

        if user_version == 1:
            self._migrate_v1_to_v2()
            user_version = 2

        if user_version == 2:
            self._migrate_v2_to_v3()
            user_version = 3

        if user_version == 3:
            self._migrate_v3_to_v4()
            user_version = 4

        if user_version == 4:
            self._migrate_v4_to_v5()
            user_version = 5

        if user_version == 5:
            self._migrate_v5_to_v6()
            user_version = 6

        if user_version != 6:
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
                user_id TEXT NOT NULL,
                expires_at_ms INTEGER NOT NULL
            )
            """
        )

    def _migrate_v1_to_v2(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS keypackages (
                user_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                kp_id INTEGER PRIMARY KEY AUTOINCREMENT,
                kp_b64 TEXT NOT NULL,
                created_ms INTEGER NOT NULL,
                issued_ms INTEGER,
                revoked_ms INTEGER
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS keypackages_device_idx
            ON keypackages (device_id, issued_ms, revoked_ms, kp_id)
            """
        )
        self._conn.execute("PRAGMA user_version = 2")

    def _migrate_v2_to_v3(self) -> None:
        session_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "user_id" not in session_columns:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
            self._conn.execute("UPDATE sessions SET user_id = device_id WHERE user_id = ''")

        kp_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(keypackages)").fetchall()}
        if "user_id" not in kp_columns:
            self._conn.execute("ALTER TABLE keypackages ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
            self._conn.execute("UPDATE keypackages SET user_id = device_id WHERE user_id = ''")
        else:
            self._conn.execute("UPDATE keypackages SET user_id = device_id WHERE user_id = ''")

        self._conn.execute("CREATE INDEX IF NOT EXISTS keypackages_user_idx ON keypackages (user_id, issued_ms, kp_id)")
        self._conn.execute("PRAGMA user_version = 3")

    def _migrate_v3_to_v4(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                conv_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_members (
                conv_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (conv_id, user_id),
                FOREIGN KEY (conv_id) REFERENCES conversations(conv_id) ON DELETE CASCADE
            )
            """
        )
        self._conn.execute("PRAGMA user_version = 4")

    def _migrate_v4_to_v5(self) -> None:
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "home_gateway" not in columns:
            self._conn.execute("ALTER TABLE conversations ADD COLUMN home_gateway TEXT NOT NULL DEFAULT ''")
        self._conn.execute("PRAGMA user_version = 5")

    def _migrate_v5_to_v6(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_events (
                event_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                ts_ms INTEGER NOT NULL,
                kind TEXT NOT NULL,
                body_json TEXT NOT NULL,
                pub_key_b64 TEXT NOT NULL,
                sig_b64 TEXT NOT NULL
            )
            """
        )
        self._conn.execute("PRAGMA user_version = 6")
