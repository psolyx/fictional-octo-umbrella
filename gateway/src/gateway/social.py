from __future__ import annotations

import base64
import binascii
import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, List

from gateway.crypto_ed25519 import verify as verify_signature


def _b64url_decode(data: str) -> bytes:
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def canonical_event_bytes(
    *, user_id: str, prev_hash: str | None, ts_ms: int, kind: str, payload: Any
) -> bytes:
    payload_obj = payload
    payload_json = json.dumps(payload_obj, separators=(",", ":"), sort_keys=True)
    body = {
        "kind": kind,
        "payload": json.loads(payload_json),
        "prev_hash": prev_hash or "",
        "ts_ms": int(ts_ms),
        "user_id": user_id,
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def compute_event_hash(canonical_bytes: bytes) -> str:
    return hashlib.sha256(canonical_bytes).hexdigest()


@dataclass
class SocialEvent:
    user_id: str
    event_hash: str
    prev_hash: str | None
    ts_ms: int
    kind: str
    payload_json: str
    sig_b64: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "event_hash": self.event_hash,
            "prev_hash": self.prev_hash,
            "ts_ms": self.ts_ms,
            "kind": self.kind,
            "payload": json.loads(self.payload_json),
            "sig_b64": self.sig_b64,
        }


class InvalidSignature(Exception):
    pass


class InvalidChain(Exception):
    pass


class CursorNotFound(Exception):
    pass


def _verify_signature(user_id: str, sig_b64: str, canonical_bytes: bytes) -> None:
    try:
        public_key = _b64url_decode(user_id)
    except (ValueError, binascii.Error):  # type: ignore[name-defined]
        raise InvalidSignature("user_id is not a valid public key")
    try:
        signature = _b64url_decode(sig_b64)
    except (ValueError, binascii.Error):  # type: ignore[name-defined]
        raise InvalidSignature("invalid signature encoding")

    try:
        verify_signature(public_key, canonical_bytes, signature)
    except ValueError:
        raise InvalidSignature("signature verification failed")


def _canon_and_hash(
    *, user_id: str, prev_hash: str | None, ts_ms: int, kind: str, payload: Any, sig_b64: str
) -> tuple[str, str]:
    canonical_bytes = canonical_event_bytes(
        user_id=user_id, prev_hash=prev_hash, ts_ms=ts_ms, kind=kind, payload=payload
    )
    _verify_signature(user_id, sig_b64, canonical_bytes)
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    event_hash = compute_event_hash(canonical_bytes)
    return payload_json, event_hash


class InMemorySocialStore:
    def __init__(self) -> None:
        self._events: dict[str, list[SocialEvent]] = {}
        self._append_seq = 0
        self._event_seq: dict[str, int] = {}
        self._lock = threading.Lock()

    def head(self, user_id: str) -> SocialEvent | None:
        with self._lock:
            events = self._events.get(user_id, [])
            return events[-1] if events else None

    def append(
        self, *, user_id: str, prev_hash: str | None, ts_ms: int, kind: str, payload: Any, sig_b64: str
    ) -> SocialEvent:
        payload_json, event_hash = _canon_and_hash(
            user_id=user_id, prev_hash=prev_hash, ts_ms=ts_ms, kind=kind, payload=payload, sig_b64=sig_b64
        )

        with self._lock:
            events = self._events.get(user_id, [])
            for existing in events:
                if existing.event_hash == event_hash:
                    return existing
            head = events[-1] if events else None
            if head is None:
                if prev_hash not in (None, ""):
                    raise InvalidChain("first event must not set prev_hash")
            elif head.event_hash != (prev_hash or ""):
                raise InvalidChain("prev_hash must reference current head")

            event = SocialEvent(
                user_id=user_id,
                event_hash=event_hash,
                prev_hash=prev_hash or None,
                ts_ms=ts_ms,
                kind=kind,
                payload_json=payload_json,
                sig_b64=sig_b64,
            )
            events.append(event)
            self._events[user_id] = events
            self._append_seq += 1
            self._event_seq[event_hash] = self._append_seq
            return event

    def list_events(self, user_id: str, *, limit: int, after_hash: str | None) -> List[SocialEvent]:
        with self._lock:
            events = self._events.get(user_id, [])
            if after_hash:
                for idx, evt in enumerate(events):
                    if evt.event_hash == after_hash:
                        return events[idx + 1 : idx + 1 + limit]
                return []
            return events[:limit]

    def list_all_events(self, user_id: str) -> List[SocialEvent]:
        with self._lock:
            return list(self._events.get(user_id, []))

    def list_posts_for_users(
        self,
        user_ids: list[str],
        *,
        limit: int,
        cursor: tuple[int, str] | None,
    ) -> List[SocialEvent]:
        with self._lock:
            events: list[SocialEvent] = []
            user_id_set = set(user_ids)
            cursor_seq = None
            if cursor:
                cursor_ts_ms, cursor_hash = cursor
                cursor_event = next(
                    (
                        social_event
                        for events_for_user in self._events.values()
                        for social_event in events_for_user
                        if social_event.event_hash == cursor_hash
                        and social_event.ts_ms == cursor_ts_ms
                        and social_event.kind == "post"
                    ),
                    None,
                )
                if cursor_event is None:
                    raise CursorNotFound("cursor not found")
                cursor_seq = self._event_seq.get(cursor_hash)
                if cursor_seq is None:
                    raise CursorNotFound("cursor not found")
            for events_for_user in self._events.values():
                for social_event in events_for_user:
                    if social_event.user_id not in user_id_set or social_event.kind != "post":
                        continue
                    if cursor and cursor_seq is not None:
                        event_seq = self._event_seq.get(social_event.event_hash)
                        if event_seq is None:
                            continue
                        if not (
                            social_event.ts_ms < cursor[0]
                            or (social_event.ts_ms == cursor[0] and event_seq < cursor_seq)
                        ):
                            continue
                    if social_event.event_hash not in self._event_seq:
                        continue
                    events.append(social_event)
            events.sort(
                key=lambda item: (item.ts_ms, self._event_seq.get(item.event_hash, 0)),
                reverse=True,
            )
            return events[:limit]


class SQLiteSocialStore:
    def __init__(self, backend) -> None:
        self._backend = backend

    def head(self, user_id: str) -> SocialEvent | None:
        with self._backend.lock:
            row = self._backend.connection.execute(
                """
                SELECT user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64
                FROM social_events
                WHERE user_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return SocialEvent(**row)

    def append(
        self, *, user_id: str, prev_hash: str | None, ts_ms: int, kind: str, payload: Any, sig_b64: str
    ) -> SocialEvent:
        payload_json, event_hash = _canon_and_hash(
            user_id=user_id, prev_hash=prev_hash, ts_ms=ts_ms, kind=kind, payload=payload, sig_b64=sig_b64
        )

        with self._backend.lock:
            conn = self._backend.connection
            existing_row = conn.execute(
                """
                SELECT user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64
                FROM social_events
                WHERE user_id = ? AND event_hash = ?
                """,
                (user_id, event_hash),
            ).fetchone()
            if existing_row:
                return SocialEvent(**existing_row)
            head_row = conn.execute(
                "SELECT event_hash FROM social_events WHERE user_id = ? ORDER BY rowid DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            head_hash = head_row[0] if head_row else None

            if head_hash is None:
                if prev_hash not in (None, ""):
                    raise InvalidChain("first event must not set prev_hash")
            elif head_hash != (prev_hash or ""):
                raise InvalidChain("prev_hash must reference current head")

            conn.execute(
                """
                INSERT INTO social_events (user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64),
            )

        return SocialEvent(
            user_id=user_id,
            event_hash=event_hash,
            prev_hash=prev_hash or None,
            ts_ms=ts_ms,
            kind=kind,
            payload_json=payload_json,
            sig_b64=sig_b64,
        )

    def list_events(self, user_id: str, *, limit: int, after_hash: str | None) -> List[SocialEvent]:
        after_rowid = 0
        if after_hash:
            with self._backend.lock:
                row = self._backend.connection.execute(
                    "SELECT rowid FROM social_events WHERE user_id = ? AND event_hash = ?",
                    (user_id, after_hash),
                ).fetchone()
                if row is None:
                    return []
                after_rowid = row[0]

        with self._backend.lock:
            rows = self._backend.connection.execute(
                """
                SELECT user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64
                FROM social_events
                WHERE user_id = ? AND rowid > ?
                ORDER BY rowid ASC
                LIMIT ?
                """,
                (user_id, after_rowid, limit),
            ).fetchall()
        return [SocialEvent(**row) for row in rows]

    def list_all_events(self, user_id: str) -> List[SocialEvent]:
        with self._backend.lock:
            rows = self._backend.connection.execute(
                """
                SELECT user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64
                FROM social_events
                WHERE user_id = ?
                ORDER BY rowid ASC
                """,
                (user_id,),
            ).fetchall()
        return [SocialEvent(**row) for row in rows]

    def list_posts_for_users(
        self,
        user_ids: list[str],
        *,
        limit: int,
        cursor: tuple[int, str] | None,
    ) -> List[SocialEvent]:
        if not user_ids:
            return []
        placeholders = ",".join("?" for _ in user_ids)
        query = (
            """
            SELECT rowid, user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64
            FROM social_events
            WHERE kind = 'post' AND user_id IN (
            """
            + placeholders
            + ")"
        )
        params: list[Any] = list(user_ids)
        if cursor:
            with self._backend.lock:
                cursor_row = self._backend.connection.execute(
                    """
                    SELECT rowid
                    FROM social_events
                    WHERE event_hash = ? AND ts_ms = ? AND kind = 'post'
                    LIMIT 1
                    """,
                    (cursor[1], cursor[0]),
                ).fetchone()
            if cursor_row is None:
                raise CursorNotFound("cursor not found")
            cursor_rowid = cursor_row[0]
            query += " AND (ts_ms < ? OR (ts_ms = ? AND rowid < ?))"
            params.extend([cursor[0], cursor[0], cursor_rowid])
        query += " ORDER BY ts_ms DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self._backend.lock:
            rows = self._backend.connection.execute(query, tuple(params)).fetchall()
        return [
            SocialEvent(
                user_id=row["user_id"],
                event_hash=row["event_hash"],
                prev_hash=row["prev_hash"],
                ts_ms=row["ts_ms"],
                kind=row["kind"],
                payload_json=row["payload_json"],
                sig_b64=row["sig_b64"],
            )
            for row in rows
        ]


def social_event_sort_key(social_event: SocialEvent) -> tuple[int, str]:
    return (int(social_event.ts_ms), social_event.event_hash)


def latest_event_by_kind(events: list[SocialEvent], kind: str) -> SocialEvent | None:
    latest: SocialEvent | None = None
    for social_event in events:
        if social_event.kind != kind:
            continue
        if latest is None or social_event_sort_key(social_event) > social_event_sort_key(latest):
            latest = social_event
    return latest


def parse_follow_payload(payload: dict[str, Any]) -> tuple[str, bool] | None:
    target_user_id = payload.get("target_user_id") or payload.get("target") or payload.get("user_id")
    if not isinstance(target_user_id, str) or not target_user_id:
        return None
    if "following" in payload:
        following = bool(payload.get("following"))
    elif "value" in payload:
        following = bool(payload.get("value"))
    elif "state" in payload:
        following = str(payload.get("state")).lower() in ("follow", "following", "true", "1")
    else:
        following = True
    return (target_user_id, following)


def decode_payload_json(social_event: SocialEvent) -> dict[str, Any]:
    parsed = json.loads(social_event.payload_json)
    return parsed if isinstance(parsed, dict) else {}


def parse_feed_cursor(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    ts_text, sep, event_hash = cursor.partition(":")
    if not sep:
        return None
    try:
        ts_ms = int(ts_text)
    except ValueError:
        return None
    if ts_ms < 0 or not event_hash:
        return None
    return (ts_ms, event_hash)
