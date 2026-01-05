from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _b64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + padding)


def derive_user_id(pub_key_b64: str) -> str:
    pub = _b64url_decode(pub_key_b64)
    digest = hashlib.sha256(pub).hexdigest()
    return f"u_{digest}"


def canonical_bytes(event: dict[str, Any]) -> bytes:
    payload = {
        "body": event["body"],
        "kind": event["kind"],
        "ts_ms": int(event["ts_ms"]),
        "user_id": event["user_id"],
        "v": int(event["v"]),
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def compute_event_id(canonical: bytes) -> str:
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class SocialEvent:
    v: int
    user_id: str
    ts_ms: int
    kind: str
    body: dict[str, Any]
    pub_key: str
    sig: str
    event_id: str


class GoEd25519Verifier:
    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[3]
        self._binary_path: Path | None = None
        self._lock = threading.Lock()

    def _go_binary(self) -> str:
        return os.environ.get("GO_BINARY") or os.environ.get("GO") or "go"

    def _ensure_binary(self) -> Path:
        with self._lock:
            if self._binary_path and self._binary_path.exists():
                return self._binary_path
            tool_dir = self.repo_root / "tools" / "polycentric_ed25519"
            binary = tool_dir / "bin" / "polycentric-ed25519"
            binary.parent.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env.setdefault("GOTOOLCHAIN", "local")
            env.setdefault("GOFLAGS", "-mod=vendor")
            subprocess.run(
                [self._go_binary(), "build", "-o", str(binary), "./cmd/polycentric-ed25519"],
                cwd=str(tool_dir),
                check=True,
                env=env,
            )
            self._binary_path = binary
            return binary

    def verify(self, pub_key_b64: str, sig_b64: str, payload: bytes) -> bool:
        try:
            binary = self._ensure_binary()
        except (OSError, subprocess.CalledProcessError):
            return False
        env = os.environ.copy()
        env.setdefault("GOTOOLCHAIN", "local")
        env.setdefault("GOFLAGS", "-mod=vendor")
        result = subprocess.run(
            [str(binary), "verify", "--pub-key-b64", pub_key_b64, "--sig-b64", sig_b64],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
        )
        return result.returncode == 0


class InMemorySocialStore:
    def __init__(self) -> None:
        self._events: list[SocialEvent] = []
        self._by_id: dict[str, SocialEvent] = {}
        self._lock = threading.Lock()

    def upsert_event(self, event: SocialEvent) -> SocialEvent:
        with self._lock:
            existing = self._by_id.get(event.event_id)
            if existing:
                return existing
            self._by_id[event.event_id] = event
            self._events.append(event)
            self._events.sort(key=lambda e: (e.ts_ms, e.event_id))
            return event

    def get_event(self, event_id: str) -> SocialEvent | None:
        with self._lock:
            return self._by_id.get(event_id)

    def list_feed(self, user_id: str, start_ts: int, start_event_id: str | None, limit: int) -> tuple[list[SocialEvent], bool]:
        with self._lock:
            filtered = [e for e in self._events if e.user_id == user_id]
            filtered = [
                e
                for e in filtered
                if e.ts_ms > start_ts or (e.ts_ms == start_ts and (start_event_id is None or e.event_id > start_event_id))
            ]
            items = filtered[: limit + 1]
            has_more = len(items) > limit
            return items[:limit], has_more


class SQLiteSocialStore:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock

    def upsert_event(self, event: SocialEvent) -> SocialEvent:
        with self._lock:
            row = self._conn.execute(
                "SELECT event_id, user_id, ts_ms, kind, body_json, pub_key_b64, sig_b64 FROM social_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if row:
                return SocialEvent(
                    v=1,
                    user_id=row["user_id"],
                    ts_ms=row["ts_ms"],
                    kind=row["kind"],
                    body=json.loads(row["body_json"]),
                    pub_key=row["pub_key_b64"],
                    sig=row["sig_b64"],
                    event_id=row["event_id"],
                )
            self._conn.execute(
                """
                INSERT INTO social_events(event_id, user_id, ts_ms, kind, body_json, pub_key_b64, sig_b64)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.user_id,
                    event.ts_ms,
                    event.kind,
                    json.dumps(event.body, sort_keys=True),
                    event.pub_key,
                    event.sig,
                ),
            )
            return event

    def get_event(self, event_id: str) -> SocialEvent | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT event_id, user_id, ts_ms, kind, body_json, pub_key_b64, sig_b64 FROM social_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if not row:
                return None
            return SocialEvent(
                v=1,
                user_id=row["user_id"],
                ts_ms=row["ts_ms"],
                kind=row["kind"],
                body=json.loads(row["body_json"]),
                pub_key=row["pub_key_b64"],
                sig=row["sig_b64"],
                event_id=row["event_id"],
            )

    def list_feed(self, user_id: str, start_ts: int, start_event_id: str | None, limit: int) -> tuple[list[SocialEvent], bool]:
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT event_id, user_id, ts_ms, kind, body_json, pub_key_b64, sig_b64
                FROM social_events
                WHERE user_id = ? AND (ts_ms > ? OR (ts_ms = ? AND event_id > ?))
                ORDER BY ts_ms ASC, event_id ASC
                LIMIT ?
                """,
                (user_id, start_ts, start_ts, start_event_id or "", limit + 1),
            )
            rows = cursor.fetchall()
            events = [
                SocialEvent(
                    v=1,
                    user_id=row["user_id"],
                    ts_ms=row["ts_ms"],
                    kind=row["kind"],
                    body=json.loads(row["body_json"]),
                    pub_key=row["pub_key_b64"],
                    sig=row["sig_b64"],
                    event_id=row["event_id"],
                )
                for row in rows
            ]
            has_more = len(events) > limit
            return events[:limit], has_more


def decode_cursor(cursor: str) -> tuple[int, str | None]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"==")
        data = json.loads(raw.decode("utf-8"))
        return int(data.get("ts", 0)), data.get("event_id")
    except Exception as exc:
        raise ValueError("invalid cursor") from exc


def encode_cursor(ts_ms: int, event_id: str) -> str:
    payload = json.dumps({"ts": ts_ms, "event_id": event_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
