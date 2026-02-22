from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cli_app.crypto_ed25519 import sign as sign_ed25519
from cli_app.crypto_ed25519 import verify as verify_ed25519

from .identity_store import IdentityRecord


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def canonical_social_bytes(
    *, user_id: str, prev_hash: str | None, ts_ms: int, kind: str, payload: Any
) -> bytes:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    normalized = json.loads(payload_json)
    body = {
        "kind": kind,
        "payload": normalized,
        "prev_hash": prev_hash or "",
        "ts_ms": int(ts_ms),
        "user_id": user_id,
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def compute_event_hash(canonical_bytes: bytes) -> str:
    return hashlib.sha256(canonical_bytes).hexdigest()


def _sign_event(identity: IdentityRecord, *, prev_hash: str | None, ts_ms: int, kind: str, payload: Any) -> tuple[str, str]:
    canonical_bytes = canonical_social_bytes(
        user_id=identity.social_public_key_b64,
        prev_hash=prev_hash,
        ts_ms=ts_ms,
        kind=kind,
        payload=payload,
    )
    signature = sign_ed25519(_b64url_decode(identity.social_private_key_b64), canonical_bytes)
    return _b64url(signature), compute_event_hash(canonical_bytes)


def _verify_event_signature(event: dict) -> None:
    canonical_bytes = canonical_social_bytes(
        user_id=event["user_id"],
        prev_hash=event.get("prev_hash") or None,
        ts_ms=int(event["ts_ms"]),
        kind=str(event["kind"]),
        payload=event["payload"],
    )
    sig = _b64url_decode(str(event["sig_b64"]))
    try:
        verify_ed25519(_b64url_decode(event["user_id"]), canonical_bytes, sig)
    except ValueError as exc:
        raise ValueError("invalid event signature") from exc
    expected_hash = compute_event_hash(canonical_bytes)
    if expected_hash != event.get("event_hash"):
        raise ValueError("event_hash does not match canonical bytes")


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _post_json(url: str, payload: dict, *, headers: dict[str, str] | None = None) -> dict:
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=all_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            return {"status": resp.status, "body": json.loads(body)}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "body": json.loads(exc.read().decode("utf-8"))}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8")
        return {"status": resp.status, "body": json.loads(body), "headers": dict(resp.headers)}


def _start_session(base_url: str, identity: IdentityRecord) -> str:
    session_url = f"{_normalize_base_url(base_url)}/v1/session/start"
    payload = {
        "auth_token": identity.auth_token,
        "device_id": identity.device_id,
        "device_credential": identity.device_credential,
    }
    result = _post_json(session_url, payload)
    if result["status"] != 200:
        raise RuntimeError(f"failed to start session: {result['body']}")
    return result["body"]["session_token"]


def fetch_social_events(base_url: str, *, user_id: str, limit: int = 50, after_hash: str | None = None) -> list[dict]:
    query = {"user_id": user_id, "limit": str(limit)}
    if after_hash:
        query["after_hash"] = after_hash
    query_string = urllib.parse.urlencode(query)
    url = f"{_normalize_base_url(base_url)}/v1/social/events?{query_string}"
    result = _get_json(url)
    if result["status"] != 200:
        raise RuntimeError(f"failed to fetch events: {result['body']}")
    events = result["body"].get("events", [])
    for event in events:
        _verify_event_signature(event)
    return events


def fetch_social_profile(base_url: str, *, user_id: str, limit: int = 20) -> dict:
    query = urllib.parse.urlencode({"user_id": user_id, "limit": str(limit)})
    url = f"{_normalize_base_url(base_url)}/v1/social/profile?{query}"
    result = _get_json(url)
    if result["status"] != 200:
        raise RuntimeError(f"failed to fetch profile: {result['body']}")
    body = result.get("body", {})
    if not isinstance(body, dict):
        raise RuntimeError("profile response was not an object")
    return body


def fetch_social_feed(
    base_url: str,
    *,
    user_id: str,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    query: dict[str, str] = {"user_id": user_id, "limit": str(limit)}
    if cursor:
        query["cursor"] = cursor
    url = f"{_normalize_base_url(base_url)}/v1/social/feed?{urllib.parse.urlencode(query)}"
    result = _get_json(url)
    if result["status"] != 200:
        raise RuntimeError(f"failed to fetch feed: {result['body']}")
    body = result.get("body", {})
    if not isinstance(body, dict):
        raise RuntimeError("feed response was not an object")
    return body


def publish_social_event(
    base_url: str,
    *,
    identity: IdentityRecord,
    kind: str,
    payload: Any,
    prev_hash: str | None = None,
) -> dict:
    normalized_base = _normalize_base_url(base_url)
    session_token = _start_session(normalized_base, identity)

    head_hash = prev_hash
    if head_hash is None:
        existing = fetch_social_events(normalized_base, user_id=identity.social_public_key_b64, limit=1)
        if existing:
            head_hash = existing[-1]["event_hash"]

    ts_ms = int(time.time() * 1000)
    signature_b64, expected_hash = _sign_event(
        identity, prev_hash=head_hash, ts_ms=ts_ms, kind=kind, payload=payload
    )
    result = _post_json(
        f"{normalized_base}/v1/social/events",
        {
            "prev_hash": head_hash,
            "ts_ms": ts_ms,
            "kind": kind,
            "payload": payload,
            "sig_b64": signature_b64,
        },
        headers={"Authorization": f"Bearer {session_token}"},
    )
    if result["status"] != 200:
        raise RuntimeError(f"publish failed: {result['body']}")
    event = result["body"]
    _verify_event_signature(event)
    if event.get("event_hash") != expected_hash:
        raise RuntimeError("gateway returned unexpected event hash")
    return event


def publish_profile_field(base_url: str, *, identity: IdentityRecord, kind: str, value: Any) -> dict:
    return publish_social_event(base_url, identity=identity, kind=kind, payload={"value": value})


def publish_post(base_url: str, *, identity: IdentityRecord, text: str) -> dict:
    return publish_social_event(base_url, identity=identity, kind="post", payload={"text": text})


def publish_follow(
    base_url: str,
    *,
    identity: IdentityRecord,
    target_user_id: str,
    following: bool,
) -> dict:
    payload = {"target_user_id": target_user_id, "following": bool(following)}
    return publish_social_event(base_url, identity=identity, kind="follow", payload=payload)
