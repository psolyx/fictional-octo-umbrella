from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict

from cli_app.identity_store import IdentityRecord
from cli_app import polycentric_ed25519


def canonical_bytes(v: int, user_id: str, ts_ms: int, kind: str, body: dict[str, Any]) -> bytes:
    payload = {"body": body, "kind": kind, "ts_ms": int(ts_ms), "user_id": user_id, "v": v}
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def compute_event_id(canonical: bytes) -> str:
    return hashlib.sha256(canonical).hexdigest()


def publish_text(base_url: str, identity: IdentityRecord, text: str) -> dict[str, Any]:
    body = {"text": text}
    ts_ms = int(time.time() * 1000)
    canonical = canonical_bytes(1, identity.user_id, ts_ms, "post", body)
    signature = polycentric_ed25519.sign(identity.seed_b64, canonical)
    event_id = compute_event_id(canonical)

    event = {
        "v": 1,
        "user_id": identity.user_id,
        "ts_ms": ts_ms,
        "kind": "post",
        "body": body,
        "pub_key": signature["pub_key_b64"],
        "sig": signature["sig_b64"],
        "event_id": event_id,
    }

    req = urllib.request.Request(
        urllib.parse.urljoin(base_url, "/v1/social/event"),
        data=json.dumps(event).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_feed(
    base_url: str, user_id: str, *, from_ts_ms: int | None = None, limit: int | None = None, cursor: str | None = None
) -> dict[str, Any]:
    query: Dict[str, Any] = {"user_id": user_id}
    if from_ts_ms is not None:
        query["from_ts_ms"] = str(from_ts_ms)
    if limit is not None:
        query["limit"] = str(limit)
    if cursor is not None:
        query["cursor"] = cursor
    query_string = urllib.parse.urlencode(query)
    url = urllib.parse.urljoin(base_url, f"/v1/social/feed?{query_string}")
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        data["cache_control"] = resp.headers.get("Cache-Control")
        return data


def fetch_event(base_url: str, event_id: str) -> dict[str, Any]:
    url = urllib.parse.urljoin(base_url, f"/v1/social/event/{urllib.parse.quote(event_id)}")
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        data["cache_control"] = resp.headers.get("Cache-Control")
        return data
