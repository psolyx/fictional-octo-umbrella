from __future__ import annotations

import asyncio
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PHASE5_2_SMOKE_LITE_BEGIN = "PHASE5_2_SMOKE_LITE_BEGIN"
PHASE5_2_SMOKE_LITE_OK = "PHASE5_2_SMOKE_LITE_OK"
PHASE5_2_SMOKE_LITE_END = "PHASE5_2_SMOKE_LITE_END"


class _HttpGateway:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _url(self, path: str, params: dict[str, str] | None = None) -> str:
        if not params:
            return f"{self.base_url}{path}"
        return f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"

    @staticmethod
    def _decode(raw: bytes) -> dict[str, Any]:
        if not raw:
            return {}
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers: dict[str, str] = {}
        body: bytes | None = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(json_body).encode("utf-8")
        req = urllib.request.Request(self._url(path, params), data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return int(resp.status), self._decode(resp.read())
        except urllib.error.HTTPError as exc:
            return int(exc.code), self._decode(exc.read())

    async def post(
        self,
        path: str,
        *,
        token: str | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return await asyncio.to_thread(self._request, "POST", path, token=token, json_body=json_body)

    async def get(
        self,
        path: str,
        *,
        token: str | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return await asyncio.to_thread(self._request, "GET", path, token=token, params=params)


class _AiohttpGateway:
    def __init__(self, client):
        self.client = client

    async def post(
        self,
        path: str,
        *,
        token: str | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        response = await self.client.post(path, headers=headers, json=json_body)
        payload = await response.json()
        return int(response.status), payload if isinstance(payload, dict) else {"value": payload}

    async def get(
        self,
        path: str,
        *,
        token: str | None = None,
        params: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        response = await self.client.get(path, headers=headers, params=params)
        payload = await response.json()
        return int(response.status), payload if isinstance(payload, dict) else {"value": payload}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _canonical_social_bytes_fallback(
    *,
    user_id: str,
    prev_hash: str | None,
    ts_ms: int,
    kind: str,
    payload: dict[str, Any],
) -> bytes:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    normalized_payload = json.loads(payload_json)
    canonical = {
        "kind": kind,
        "payload": normalized_payload,
        "prev_hash": prev_hash or "",
        "ts_ms": int(ts_ms),
        "user_id": user_id,
    }
    return json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _load_social_crypto():
    try:
        from gateway.crypto_ed25519 import generate_keypair, sign
        from gateway.social import canonical_event_bytes

        return generate_keypair, sign, canonical_event_bytes
    except Exception:
        from cli_app.crypto_ed25519 import generate_keypair, sign

        return generate_keypair, sign, _canonical_social_bytes_fallback


async def _run(adapter, *, out) -> int:
    step = 1

    def emit(line: str) -> None:
        out.write(line + "\n")

    def ok(label: str, **fields: object) -> None:
        nonlocal step
        detail = " ".join(f"{k}={v}" for k, v in fields.items())
        suffix = f" {detail}" if detail else ""
        emit(f"step={step} ok {label}{suffix}")
        step += 1

    def fail(label: str, reason: str) -> int:
        nonlocal step
        emit(f"step={step} FAIL {label} reason={reason}")
        emit(PHASE5_2_SMOKE_LITE_END)
        return 1

    emit(PHASE5_2_SMOKE_LITE_BEGIN)
    users = {"alice": "u_phase5_2_alice", "bob": "u_phase5_2_bob"}

    status, alice_start = await adapter.post(
        "/v1/session/start",
        json_body={"auth_token": f"Bearer {users['alice']}", "device_id": "d_phase5_2_alice_main"},
    )
    if status != 200:
        return fail("session_start_alice", "status_not_200")
    alice_token = str(alice_start.get("session_token", ""))
    if not alice_token:
        return fail("session_start_alice", "missing_session_token")
    ok("session_start_alice", device_id="d_phase5_2_alice_main")

    status, bob_start = await adapter.post(
        "/v1/session/start",
        json_body={"auth_token": f"Bearer {users['bob']}", "device_id": "d_phase5_2_bob_main"},
    )
    if status != 200:
        return fail("session_start_bob", "status_not_200")
    bob_token = str(bob_start.get("session_token", ""))
    if not bob_token:
        return fail("session_start_bob", "missing_session_token")
    ok("session_start_bob", device_id="d_phase5_2_bob_main")

    status, listed = await adapter.get("/v1/session/list", token=alice_token)
    if status != 200:
        return fail("session_list_alice_initial", "status_not_200")
    listed_rows = listed.get("sessions", [])
    if not isinstance(listed_rows, list) or len(listed_rows) != 1:
        return fail("session_list_alice_initial", "unexpected_session_count")
    if listed_rows != sorted(
        listed_rows,
        key=lambda row: (not bool(row.get("is_current")), str(row.get("device_id", "")), str(row.get("session_id", ""))),
    ):
        return fail("session_list_alice_initial", "non_deterministic_order")
    ok("session_list_alice_initial", count=len(listed_rows))

    status, alt_start = await adapter.post(
        "/v1/session/start",
        json_body={"auth_token": f"Bearer {users['alice']}", "device_id": "d_phase5_2_alice_alt"},
    )
    if status != 200:
        return fail("session_start_alice_alt", "status_not_200")
    alice_alt_token = str(alt_start.get("session_token", ""))
    if not alice_alt_token:
        return fail("session_start_alice_alt", "missing_session_token")
    ok("session_start_alice_alt", device_id="d_phase5_2_alice_alt")

    status, listed_after = await adapter.get("/v1/session/list", token=alice_token)
    if status != 200:
        return fail("session_list_alice_after_alt", "status_not_200")
    sessions = listed_after.get("sessions", [])
    target_rows = [row for row in sessions if row.get("device_id") == "d_phase5_2_alice_alt"]
    if len(target_rows) != 1 or not target_rows[0].get("session_id"):
        return fail("session_list_alice_after_alt", "missing_alt_session")
    revoke_session_id = str(target_rows[0]["session_id"])
    ok("session_list_alice_after_alt", count=len(sessions), revoked_device_id="d_phase5_2_alice_alt")

    status, revoke = await adapter.post(
        "/v1/session/revoke",
        token=alice_token,
        json_body={"session_id": revoke_session_id, "include_self": False},
    )
    if status != 200 or int(revoke.get("revoked", 0)) != 1:
        return fail("session_revoke_alt", "revoke_failed")
    ok("session_revoke_alt", session_id=revoke_session_id)

    status, _ = await adapter.get("/v1/conversations", token=alice_alt_token)
    if status != 401:
        return fail("revoked_token_rejected", "expected_401")
    ok("revoked_token_rejected", status=status)

    dm_conv_id = "dm_phase5_2_smoke"
    status, dm_create = await adapter.post(
        "/v1/dms/create",
        token=alice_token,
        json_body={"peer_user_id": users["bob"], "conv_id": dm_conv_id},
    )
    if status != 200 or str(dm_create.get("conv_id", "")) != dm_conv_id:
        return fail("dm_create", "create_failed")
    ok("dm_create", conv_id=dm_conv_id)

    for msg_id, ts_ms in (("m_phase5_2_dm_1", 1001), ("m_phase5_2_dm_2", 1002)):
        status, inbox = await adapter.post(
            "/v1/inbox",
            token=alice_token,
            json_body={
                "v": 1,
                "t": "conv.send",
                "body": {"conv_id": dm_conv_id, "msg_id": msg_id, "env": "ZW52", "ts": ts_ms},
            },
        )
        if status != 200:
            return fail("dm_send", "send_failed")
        ok("dm_send", conv_id=dm_conv_id, msg_id=msg_id, seq=int(inbox.get("seq", 0)))

    def find_conv(items: Any, conv_id: str) -> dict[str, Any] | None:
        if not isinstance(items, list):
            return None
        for row in items:
            if isinstance(row, dict) and row.get("conv_id") == conv_id:
                return row
        return None

    status, alice_convs = await adapter.get("/v1/conversations", token=alice_token)
    if status != 200:
        return fail("conversations_list_alice", "status_not_200")
    status, bob_convs = await adapter.get("/v1/conversations", token=bob_token)
    if status != 200:
        return fail("conversations_list_bob", "status_not_200")
    alice_dm = find_conv(alice_convs.get("items", []), dm_conv_id)
    bob_dm = find_conv(bob_convs.get("items", []), dm_conv_id)
    if alice_dm is None or bob_dm is None:
        return fail("dm_visible_in_lists", "dm_missing")
    bob_unread = int(bob_dm.get("unread_count", -1))
    if bob_unread < 1:
        return fail("dm_unread_counts", "bob_unread_not_incremented")
    bob_latest_seq = int(bob_dm.get("latest_seq", 0))
    if bob_latest_seq < 2:
        return fail("dm_unread_counts", "missing_latest_seq")
    ok("dm_unread_counts", alice_unread=alice_dm.get("unread_count"), bob_unread=bob_unread)

    status, _ = await adapter.post(
        "/v1/conversations/mark_read",
        token=bob_token,
        json_body={"conv_id": dm_conv_id, "to_seq": bob_latest_seq},
    )
    if status != 200:
        return fail("dm_mark_read_bob", "mark_read_failed")
    status, bob_after = await adapter.get("/v1/conversations", token=bob_token)
    if status != 200:
        return fail("dm_mark_read_bob", "list_after_failed")
    bob_dm_after = find_conv(bob_after.get("items", []), dm_conv_id)
    if bob_dm_after is None or int(bob_dm_after.get("unread_count", -1)) != 0:
        return fail("dm_mark_read_bob", "unread_not_cleared")
    ok("dm_mark_read_bob", unread_count=bob_dm_after.get("unread_count"))

    room_conv_id = "conv_phase5_2_room"
    status, _ = await adapter.post(
        "/v1/rooms/create",
        token=alice_token,
        json_body={"conv_id": room_conv_id, "members": [users["bob"]]},
    )
    if status != 200:
        return fail("room_create", "create_failed")
    status, room_members = await adapter.get("/v1/rooms/members", token=alice_token, params={"conv_id": room_conv_id})
    expected_members = [
        {"user_id": users["alice"], "role": "owner"},
        {"user_id": users["bob"], "role": "member"},
    ]
    if status != 200 or room_members.get("members") != expected_members:
        return fail("room_members", "unexpected_member_order")
    ok("room_members", conv_id=room_conv_id, member_count=len(expected_members))

    status, _ = await adapter.post(
        "/v1/inbox",
        token=alice_token,
        json_body={
            "v": 1,
            "t": "conv.send",
            "body": {"conv_id": room_conv_id, "msg_id": "m_phase5_2_room_1", "env": "cm9vbQ==", "ts": 2001},
        },
    )
    if status != 200:
        return fail("room_send", "send_failed")
    ok("room_send", conv_id=room_conv_id, msg_id="m_phase5_2_room_1")

    generate_keypair, sign_event, canonical_event_bytes = _load_social_crypto()
    seed, public = generate_keypair()
    social_user_id = _b64url(public)
    status, social_start = await adapter.post(
        "/v1/session/start",
        json_body={"auth_token": f"Bearer {social_user_id}", "device_id": "d_phase5_2_social"},
    )
    if status != 200:
        return fail("social_session_start", "status_not_200")
    social_token = str(social_start.get("session_token", ""))
    prev_hash: str | None = None
    for ts_ms, kind, payload in [
        (3001, "username", {"value": "phase5_2_alice"}),
        (3002, "description", {"value": "phase5_2_description"}),
        (3003, "interests", {"value": "phase5_2_interest"}),
        (3004, "post", {"value": "phase5_2_post_1"}),
        (3005, "follow", {"target_user_id": users["bob"], "following": True}),
    ]:
        canonical = canonical_event_bytes(
            user_id=social_user_id,
            prev_hash=prev_hash,
            ts_ms=ts_ms,
            kind=kind,
            payload=payload,
        )
        sig_b64 = _b64url(sign_event(seed, canonical))
        status, published = await adapter.post(
            "/v1/social/events",
            token=social_token,
            json_body={"prev_hash": prev_hash, "ts_ms": ts_ms, "kind": kind, "payload": payload, "sig_b64": sig_b64},
        )
        if status != 200 or not published.get("event_hash"):
            return fail("social_publish", f"publish_failed_{kind}")
        prev_hash = str(published["event_hash"])
        ok("social_publish", user_id=social_user_id, kind=kind)

    status, profile = await adapter.get("/v1/social/profile", params={"user_id": social_user_id, "limit": "5"})
    if status != 200:
        return fail("social_profile", "status_not_200")
    if profile.get("username") != "phase5_2_alice" or profile.get("description") != "phase5_2_description":
        return fail("social_profile", "profile_fields_mismatch")
    if profile.get("interests") != "phase5_2_interest" or profile.get("friends") != [users["bob"]]:
        return fail("social_profile", "profile_social_mismatch")
    ok("social_profile", user_id=social_user_id)

    status, feed = await adapter.get("/v1/social/feed", params={"user_id": social_user_id, "limit": "10"})
    items = feed.get("items", []) if status == 200 else []
    first_item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    if status != 200 or first_item.get("kind") != "post" or first_item.get("payload", {}).get("value") != "phase5_2_post_1":
        return fail("social_feed", "unexpected_order")
    ok("social_feed", item_count=len(items))

    status, _ = await adapter.post(
        "/v1/inbox",
        token=bob_token,
        json_body={
            "v": 1,
            "t": "conv.send",
            "body": {"conv_id": room_conv_id, "msg_id": "m_phase5_2_room_2", "env": "cm9vbQ==", "ts": 2002},
        },
    )
    if status != 200:
        return fail("mark_all_read_setup", "setup_send_failed")
    status, alice_before = await adapter.get("/v1/conversations", token=alice_token)
    room_before = find_conv(alice_before.get("items", []), room_conv_id) if status == 200 else None
    if status != 200 or room_before is None or int(room_before.get("unread_count", 0)) <= 0:
        return fail("mark_all_read_setup", "missing_unread")

    status, _ = await adapter.post("/v1/conversations/mark_all_read", token=alice_token, json_body={})
    if status != 200:
        return fail("mark_all_read", "mark_all_failed")
    status, alice_after = await adapter.get("/v1/conversations", token=alice_token)
    if status != 200:
        return fail("mark_all_read", "list_after_failed")
    for row in alice_after.get("items", []):
        if int(row.get("unread_count", 0)) != 0:
            return fail("mark_all_read", "unread_not_zero")
    ok("mark_all_read", conv_count=len(alice_after.get("items", [])))

    emit(PHASE5_2_SMOKE_LITE_OK)
    emit(PHASE5_2_SMOKE_LITE_END)
    return 0


async def run_smoke_lite_http(base_url: str, *, out) -> int:
    return await _run(_HttpGateway(base_url), out=out)


async def run_smoke_lite_testclient(client, *, out) -> int:
    return await _run(_AiohttpGateway(client), out=out)
