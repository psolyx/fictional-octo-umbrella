from __future__ import annotations

import asyncio
import importlib
import json
import os
import secrets
from email.utils import formatdate
from typing import Any, Callable, List, Tuple, TypedDict, Union

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is not None:  # pragma: no cover - exercised in CI with deps
    from aiohttp import WSMsgType, web
else:  # pragma: no cover - offline fallback
    from gateway.aiohttp_stub import WSMsgType, web

from .conversations import InMemoryConversationStore, SQLiteConversationStore
from .cursors import CursorStore
from .hub import Subscription, SubscriptionHub
# In-memory conversation log implementation used when SQLite durability is disabled.
from .keypackages import InMemoryKeyPackageStore, SQLiteKeyPackageStore
from .log import ConversationEvent, ConversationLog
from .presence import FixedWindowRateLimiter, LimitExceeded, Presence, RateLimitExceeded
from .retention import ReplayWindowExceeded, RetentionPolicy, load_retention_policy_from_env
from .social import (
    CursorNotFound,
    InMemorySocialStore,
    InvalidChain,
    InvalidSignature,
    SQLiteSocialStore,
    decode_payload_json,
    latest_event_by_kind,
    parse_feed_cursor,
    parse_follow_payload,
)
from .sqlite_backend import SQLiteBackend
from .sqlite_cursors import SQLiteCursorStore
from .sqlite_log import SQLiteConversationLog
from .sqlite_sessions import Session, SQLiteSessionStore, _now_ms


_KEYPACKAGE_FETCH_LIMIT_PER_MIN = 60


class WsConfig(TypedDict):
    ping_interval_s: int
    ping_miss_limit: int
    max_msg_size: int


class SessionStore:
    """Tracks active sessions keyed by both session and resume tokens."""

    def __init__(self, ttl_ms: int = 60 * 60 * 1000) -> None:
        self._ttl_ms = ttl_ms
        self._by_session: dict[str, Session] = {}
        self._by_resume: dict[str, Session] = {}

    def create(self, user_id: str, device_id: str) -> Session:
        now_ms = _now_ms()
        session = Session(
            user_id=user_id,
            device_id=device_id,
            session_token=f"st_{secrets.token_urlsafe(16)}",
            resume_token=f"rt_{secrets.token_urlsafe(16)}",
            expires_at_ms=now_ms + self._ttl_ms,
        )
        self._by_session[session.session_token] = session
        self._by_resume[session.resume_token] = session
        return session

    def get_by_session(self, session_token: str) -> Session | None:
        session = self._by_session.get(session_token)
        if session is None:
            return None
        if session.expires_at_ms <= _now_ms():
            self.invalidate(session)
            return None
        return session

    def get_by_resume(self, resume_token: str) -> Session | None:
        session = self._by_resume.get(resume_token)
        if session is None:
            return None
        if session.expires_at_ms <= _now_ms():
            self.invalidate(session)
            return None
        return session

    def consume_resume(self, resume_token: str) -> Session | None:
        session = self._by_resume.pop(resume_token, None)
        if session is None:
            return None
        if session.expires_at_ms <= _now_ms():
            self.invalidate(session)
            return None
        session.resume_token = f"rt_{secrets.token_urlsafe(16)}"
        session.expires_at_ms = _now_ms() + self._ttl_ms
        self._by_resume[session.resume_token] = session
        return session

    def rotate_resume(self, session: Session) -> Session:
        old_token = session.resume_token
        session.resume_token = f"rt_{secrets.token_urlsafe(16)}"
        session.expires_at_ms = _now_ms() + self._ttl_ms
        self._by_resume.pop(old_token, None)
        self._by_resume[session.resume_token] = session
        return session

    def invalidate(self, session: Session) -> None:
        self._by_session.pop(session.session_token, None)
        self._by_resume.pop(session.resume_token, None)


class Runtime:
    def __init__(
        self,
        *,
        log: ConversationLog,
        cursors: CursorStore,
        hub: SubscriptionHub,
        sessions: SessionStore,
        keypackages,
        backend: SQLiteBackend | None = None,
        presence: Presence,
        keypackage_fetch_limiter: FixedWindowRateLimiter,
        now_func: Callable[[], int] = _now_ms,
        conversations,
        gateway_id: str,
        gateway_public_url: str,
        gateway_directory: dict[str, str],
        social,
        retention_policy: RetentionPolicy | None = None,
    ) -> None:
        self.log = log
        self.cursors = cursors
        self.hub = hub
        self.sessions = sessions
        self.keypackages = keypackages
        self.backend = backend
        self.presence = presence
        self.keypackage_fetch_limiter = keypackage_fetch_limiter
        self.now_func = now_func
        self.conversations = conversations
        self.gateway_id = gateway_id
        self.gateway_public_url = gateway_public_url
        self.gateway_directory = gateway_directory
        self.social = social
        self.retention_policy = retention_policy
        self.retention_task: asyncio.Task[None] | None = None


if hasattr(web, "AppKey"):
    RUNTIME_KEY: web.AppKey[Runtime] = web.AppKey("runtime", Runtime)
    WS_CONFIG_KEY: web.AppKey[WsConfig] = web.AppKey("ws_config", WsConfig)
else:  # pragma: no cover - aiohttp stub fallback
    RUNTIME_KEY = "runtime"
    WS_CONFIG_KEY = "ws_config"


async def handle_health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def _unauthorized() -> web.Response:
    return web.json_response({"code": "unauthorized", "message": "invalid session_token"}, status=401)


def _invalid_request(message: str) -> web.Response:
    return web.json_response({"code": "invalid_request", "message": message}, status=400)


def _resume_failed() -> web.Response:
    return web.json_response({"code": "resume_failed", "message": "resume token invalid or expired"}, status=401)


def _rate_limited(message: str) -> web.Response:
    return web.json_response({"code": "rate_limited", "message": message}, status=429)


def _limit_exceeded(message: str) -> web.Response:
    return web.json_response({"code": "limit_exceeded", "message": message}, status=429)


def _forbidden(message: str) -> web.Response:
    return web.json_response({"code": "forbidden", "message": message}, status=403)


def _routing_metadata(runtime: Runtime, conv_id: str) -> dict[str, str]:
    conv_home = runtime.conversations.home_gateway(conv_id, runtime.gateway_id)
    return {"conv_home": conv_home, "origin_gateway": runtime.gateway_id}


def _with_no_store(response: web.Response) -> web.Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _with_cache(response: web.Response, *, etag: str | None, last_modified_ms: int | None) -> web.Response:
    response.headers["Cache-Control"] = "public, max-age=30"
    if etag:
        response.headers["ETag"] = etag
    if last_modified_ms is not None:
        response.headers["Last-Modified"] = formatdate(last_modified_ms / 1000, usegmt=True)
    return response


class SSEWriter:
    def __init__(self, response: web.StreamResponse, on_disconnect: Callable[[], None]) -> None:
        self._response = response
        self._on_disconnect = on_disconnect

    async def send_event(self, event_type: str, data: str) -> bool:
        frame = f"event: {event_type}\n" f"data: {data}\n\n"
        return await self._write(frame.encode("utf-8"))

    async def send_ping(self) -> bool:
        return await self._write(b": ping\n\n")

    async def _write(self, payload: bytes) -> bool:
        try:
            await self._response.write(payload)
            return True
        except ConnectionResetError:
            self._on_disconnect()
            return False


def _derive_user_id(auth_token: str) -> str:
    if auth_token.startswith("Bearer "):
        return auth_token[len("Bearer ") :].strip()
    return auth_token


def _authenticate_request(request: web.Request) -> Session | None:
    runtime: Runtime = request.app[RUNTIME_KEY]
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    session_token = auth_header[len("Bearer ") :].strip()
    return runtime.sessions.get_by_session(session_token)


def _session_ready_body(runtime: Runtime, session: Session) -> dict[str, Any]:
    cursor_rows = runtime.cursors.list_cursors(session.device_id)
    return {
        "user_id": session.user_id,
        "session_token": session.session_token,
        "resume_token": session.resume_token,
        "expires_at": session.expires_at_ms,
        "cursors": [{"conv_id": conv_id, "next_seq": next_seq} for conv_id, next_seq in cursor_rows],
    }


def _validate_session_start_body(body: dict[str, Any]) -> Tuple[tuple[str, str] | None, str | None]:
    auth_token = body.get("auth_token")
    device_id = body.get("device_id")
    device_credential = body.get("device_credential")
    if not auth_token or not device_id:
        return None, "auth_token and device_id required"
    if not isinstance(auth_token, str) or not isinstance(device_id, str):
        return None, "auth_token and device_id must be strings"
    if device_credential is not None and not isinstance(device_credential, str):
        return None, "device_credential must be a string if provided"
    user_id = _derive_user_id(auth_token)
    return (user_id, device_id), None


def _load_gateway_directory(directory_path: str | None) -> dict[str, str]:
    if not directory_path:
        return {}

    try:
        with open(directory_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise ValueError("gateway directory file not found") from None
    except json.JSONDecodeError as exc:
        raise ValueError("invalid gateway directory JSON") from exc

    gateways = data.get("gateways") if isinstance(data, dict) else None
    if not isinstance(gateways, dict):
        raise ValueError("gateway directory must contain a gateways object")

    directory: dict[str, str] = {}
    for gateway_id, gateway_url in gateways.items():
        if isinstance(gateway_id, str) and isinstance(gateway_url, str):
            directory[gateway_id] = gateway_url
    return directory


def _validate_session_resume_body(body: dict[str, Any]) -> Tuple[str | None, str | None]:
    resume_token = body.get("resume_token")
    if not resume_token:
        return None, "resume_token required"
    if not isinstance(resume_token, str):
        return None, "resume_token must be a string"
    return resume_token, None


def _process_conv_send(runtime: Runtime, session: Session, body: dict[str, Any]) -> tuple[int | None, ConversationEvent | None, tuple[str, str] | None]:
    conv_id = body.get("conv_id")
    msg_id = body.get("msg_id")
    env = body.get("env")
    ts = body.get("ts") or _now_ms()
    if not conv_id or not msg_id or env is None:
        return None, None, ("invalid_request", "conv_id, msg_id, env required")
    if not runtime.conversations.is_known(conv_id) or not runtime.conversations.is_member(conv_id, session.user_id):
        return None, None, ("forbidden", "not a member")
    seq, event, created = runtime.log.append(conv_id, msg_id, env, session.device_id, ts)
    if created:
        _opportunistic_prune(runtime, conv_id)
        runtime.hub.broadcast(event)
    return seq, event, None


def _sqlite_active_min_next_seq(runtime: Runtime, conv_id: str, now_ms: int) -> int | None:
    if runtime.retention_policy is None or not isinstance(runtime.cursors, SQLiteCursorStore):
        return None
    return runtime.cursors.active_min_next_seq(
        conv_id,
        now_ms,
        runtime.retention_policy.cursor_stale_after_ms,
    )


def _opportunistic_prune(runtime: Runtime, conv_id: str) -> int:
    if runtime.retention_policy is None or not runtime.retention_policy.enabled:
        return 0
    if not isinstance(runtime.log, SQLiteConversationLog):
        return 0
    now_ms = runtime.now_func()
    return runtime.log.prune_conv(
        conv_id,
        runtime.retention_policy,
        now_ms,
        _sqlite_active_min_next_seq(runtime, conv_id, now_ms),
    )


def _replay_window_exceeded_response(exc: ReplayWindowExceeded) -> web.Response:
    return web.json_response(
        {
            "code": "replay_window_exceeded",
            "message": "requested history has been pruned",
            "earliest_seq": exc.earliest_seq,
            "latest_seq": exc.latest_seq,
        },
        status=410,
    )


def _process_conv_ack(runtime: Runtime, session: Session, body: dict[str, Any]) -> tuple[str, str] | None:
    conv_id = body.get("conv_id")
    seq = body.get("seq")
    if not conv_id or seq is None:
        return "invalid_request", "conv_id and seq required"
    if not runtime.conversations.is_known(conv_id) or not runtime.conversations.is_member(conv_id, session.user_id):
        return "forbidden", "not a member"
    runtime.cursors.ack(session.device_id, conv_id, int(seq))
    return None


async def handle_keypackage_publish(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    device_id = body.get("device_id")
    keypackages = body.get("keypackages")
    if not isinstance(device_id, str) or not isinstance(keypackages, list) or any(
        not isinstance(kp, str) for kp in keypackages
    ):
        return _invalid_request("device_id and keypackages required")
    if device_id != session.device_id:
        return _unauthorized()

    runtime.keypackages.publish(session.user_id, device_id, keypackages)
    response_body = {
        "status": "ok",
        "served_by": runtime.gateway_id,
        "user_home_gateway": runtime.gateway_id,
    }
    return web.json_response(response_body)


async def handle_keypackage_fetch(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    user_id = body.get("user_id")
    count = body.get("count")
    if not isinstance(user_id, str) or not isinstance(count, int) or count < 0:
        return _invalid_request("user_id and count required")

    now_ms = runtime.now_func()
    if not runtime.keypackage_fetch_limiter.allow(session.user_id, now_ms):
        return _rate_limited("keypackage fetch rate limit exceeded")

    keypackages = runtime.keypackages.fetch(user_id, count)
    response_body = {
        "keypackages": keypackages,
        "served_by": runtime.gateway_id,
        "user_home_gateway": runtime.gateway_id,
    }
    return web.json_response(response_body)


async def handle_keypackage_rotate(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    device_id = body.get("device_id")
    revoke = body.get("revoke", False)
    replacement = body.get("replacement") or []
    if (
        not isinstance(device_id, str)
        or not isinstance(revoke, bool)
        or not isinstance(replacement, list)
        or any(not isinstance(kp, str) for kp in replacement)
    ):
        return _invalid_request("device_id and replacement required")
    if device_id != session.device_id:
        return _unauthorized()
    runtime.keypackages.rotate(session.user_id, device_id, bool(revoke), replacement)
    response_body = {
        "status": "ok",
        "served_by": runtime.gateway_id,
        "user_home_gateway": runtime.gateway_id,
    }
    return web.json_response(response_body)


def _no_store_response(data: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(data, status=status)
    return _with_no_store(response)


async def handle_session_start_http(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return _no_store_response({"code": "invalid_request", "message": "malformed json"}, status=400)

    parsed, error = _validate_session_start_body(body if isinstance(body, dict) else {})
    if error:
        return _no_store_response({"code": "invalid_request", "message": error}, status=400)

    assert parsed is not None
    user_id, device_id = parsed
    session = runtime.sessions.create(user_id, device_id)
    ready_body = _session_ready_body(runtime, session)
    return _no_store_response(ready_body)


async def handle_session_resume_http(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    try:
        body = await request.json()
    except Exception:
        return _no_store_response({"code": "invalid_request", "message": "malformed json"}, status=400)

    parsed, error = _validate_session_resume_body(body if isinstance(body, dict) else {})
    if error:
        return _no_store_response({"code": "invalid_request", "message": error}, status=400)

    resume_token = parsed
    assert resume_token is not None
    session = runtime.sessions.consume_resume(resume_token)
    if session is None:
        return _no_store_response({"code": "resume_failed", "message": "resume token invalid or expired"}, status=401)

    ready_body = _session_ready_body(runtime, session)
    return _no_store_response(ready_body)


async def handle_presence_lease(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _with_no_store(_unauthorized())
    try:
        body = await request.json()
    except Exception:
        return _with_no_store(_invalid_request("malformed json"))

    device_id = body.get("device_id")
    ttl_seconds = body.get("ttl_seconds")
    invisible = bool(body.get("invisible", False))
    if not isinstance(device_id, str) or not isinstance(ttl_seconds, int):
        return _with_no_store(_invalid_request("device_id and ttl_seconds required"))
    if device_id != session.device_id:
        return _with_no_store(_unauthorized())
    try:
        expires_at = runtime.presence.lease(session.user_id, device_id, ttl_seconds, invisible=invisible)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    return _no_store_response({"status": "ok", "expires_at": expires_at})


async def handle_presence_renew(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _with_no_store(_unauthorized())
    try:
        body = await request.json()
    except Exception:
        return _with_no_store(_invalid_request("malformed json"))

    device_id = body.get("device_id")
    ttl_seconds = body.get("ttl_seconds")
    invisible = body.get("invisible")
    if not isinstance(device_id, str) or not isinstance(ttl_seconds, int):
        return _with_no_store(_invalid_request("device_id and ttl_seconds required"))
    if invisible is not None and not isinstance(invisible, bool):
        return _with_no_store(_invalid_request("invisible must be a boolean if provided"))
    if device_id != session.device_id:
        return _with_no_store(_unauthorized())
    try:
        expires_at = runtime.presence.renew(session.user_id, device_id, ttl_seconds, invisible=invisible)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    return _no_store_response({"status": "ok", "expires_at": expires_at})


async def handle_presence_watch(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _with_no_store(_unauthorized())
    try:
        body = await request.json()
    except Exception:
        return _with_no_store(_invalid_request("malformed json"))

    contacts = body.get("contacts")
    if not isinstance(contacts, list) or any(not isinstance(c, str) for c in contacts):
        return _with_no_store(_invalid_request("contacts must be a list of user_ids"))
    try:
        runtime.presence.watch(session.user_id, contacts)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    except LimitExceeded as exc:
        return _with_no_store(_limit_exceeded(str(exc)))
    return _no_store_response({"status": "ok", "watching": runtime.presence.watchlist_size(session.user_id)})


async def handle_presence_unwatch(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _with_no_store(_unauthorized())
    try:
        body = await request.json()
    except Exception:
        return _with_no_store(_invalid_request("malformed json"))

    contacts = body.get("contacts")
    if not isinstance(contacts, list) or any(not isinstance(c, str) for c in contacts):
        return _with_no_store(_invalid_request("contacts must be a list of user_ids"))
    try:
        runtime.presence.unwatch(session.user_id, contacts)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    return _no_store_response({"status": "ok", "watching": runtime.presence.watchlist_size(session.user_id)})


async def handle_presence_block(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _with_no_store(_unauthorized())
    try:
        body = await request.json()
    except Exception:
        return _with_no_store(_invalid_request("malformed json"))

    contacts = body.get("contacts")
    if not isinstance(contacts, list) or any(not isinstance(c, str) for c in contacts):
        return _with_no_store(_invalid_request("contacts must be a list of user_ids"))
    try:
        runtime.presence.block(session.user_id, contacts)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    except LimitExceeded as exc:
        return _with_no_store(_limit_exceeded(str(exc)))
    return _no_store_response({"status": "ok", "blocked": runtime.presence.blocklist_size(session.user_id)})


async def handle_presence_unblock(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _with_no_store(_unauthorized())
    try:
        body = await request.json()
    except Exception:
        return _with_no_store(_invalid_request("malformed json"))

    contacts = body.get("contacts")
    if not isinstance(contacts, list) or any(not isinstance(c, str) for c in contacts):
        return _with_no_store(_invalid_request("contacts must be a list of user_ids"))
    try:
        runtime.presence.unblock(session.user_id, contacts)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    return _no_store_response({"status": "ok", "blocked": runtime.presence.blocklist_size(session.user_id)})


async def handle_inbox(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    if not isinstance(body, dict) or body.get("v") != 1:
        return _invalid_request("invalid frame envelope")

    frame_type = body.get("t")
    frame_body = body.get("body") or {}

    if frame_type == "conv.send":
        seq, _, error = _process_conv_send(runtime, session, frame_body)
        if error:
            code, message = error
            if code == "forbidden":
                return _forbidden(message)
            return _invalid_request(message)
        assert seq is not None
        return web.json_response({"status": "ok", "seq": seq, **_routing_metadata(runtime, frame_body.get("conv_id"))})
    if frame_type == "conv.ack":
        error = _process_conv_ack(runtime, session, frame_body)
        if error:
            code, message = error
            if code == "forbidden":
                return _forbidden(message)
            return _invalid_request(message)
        return web.json_response({"status": "ok"})

    return _invalid_request("unsupported frame type")


async def handle_sse(request: web.Request) -> web.StreamResponse:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()

    conv_id = request.query.get("conv_id")
    if not conv_id:
        return _invalid_request("conv_id required")

    from_seq_param = request.query.get("from_seq")
    after_seq_param = request.query.get("after_seq")

    if from_seq_param is not None:
        try:
            from_seq = int(from_seq_param)
        except ValueError:
            return _invalid_request("from_seq must be an integer")
    elif after_seq_param is not None:
        try:
            from_seq = int(after_seq_param) + 1
        except ValueError:
            return _invalid_request("after_seq must be an integer")
    else:
        from_seq = runtime.cursors.next_seq(session.device_id, conv_id)

    if from_seq < 1:
        return _invalid_request("from_seq must be at least 1")

    if not runtime.conversations.is_known(conv_id) or not runtime.conversations.is_member(conv_id, session.user_id):
        return _forbidden("not a member")

    try:
        events = runtime.log.list_from(conv_id, from_seq)
    except ReplayWindowExceeded as exc:
        return _replay_window_exceeded_response(exc)

    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store"},
    )
    await response.prepare(request)

    outbound: asyncio.Queue[ConversationEvent | None] = asyncio.Queue()
    stop_event = asyncio.Event()
    buffering = True
    buffered_events: list[ConversationEvent] = []
    revoked = False

    def stop_subscription(subscription: Subscription | None) -> None:
        nonlocal revoked
        if revoked:
            return
        revoked = True
        if subscription is not None:
            runtime.hub.unsubscribe(subscription)
        stop_event.set()

    def guarded_enqueue(event: ConversationEvent, subscription: Subscription | None) -> None:
        if revoked:
            return
        if not runtime.conversations.is_member(event.conv_id, session.user_id):
            stop_subscription(subscription)
            return
        try:
            outbound.put_nowait(event)
        except asyncio.QueueFull:
            stop_subscription(subscription)

    def buffering_enqueue(event: ConversationEvent, subscription: Subscription | None) -> None:
        if revoked:
            return
        if buffering:
            buffered_events.append(event)
            return
        guarded_enqueue(event, subscription)

    subscription: Subscription | None = None

    def subscription_callback(event: ConversationEvent) -> None:
        buffering_enqueue(event, subscription)

    subscription = runtime.hub.subscribe(session.device_id, conv_id, subscription_callback)
    sse_writer = SSEWriter(response, lambda: stop_subscription(subscription))

    for event in events:
        guarded_enqueue(event, subscription)

    buffering = False
    for event in buffered_events:
        guarded_enqueue(event, subscription)

    async def keepalive() -> None:
        try:
            while not stop_event.is_set():
                await asyncio.sleep(15)
                if stop_event.is_set():
                    break
                if not await sse_writer.send_ping():
                    break
        except asyncio.CancelledError:
            return

    async def stop_watcher() -> None:
        await stop_event.wait()
        try:
            outbound.put_nowait(None)
        except asyncio.QueueFull:
            pass

    keepalive_task = asyncio.create_task(keepalive())
    watcher_task = asyncio.create_task(stop_watcher())

    try:
        while True:
            event = await outbound.get()
            if event is None:
                break
            payload = {
                "v": 1,
                "t": "conv.event",
                "body": {
                    "conv_id": event.conv_id,
                    "seq": event.seq,
                    "msg_id": event.msg_id,
                    "env": event.envelope_b64,
                    "sender_device_id": event.sender_device_id,
                    **_routing_metadata(runtime, event.conv_id),
                },
            }
            data = json.dumps(payload)
            if not await sse_writer.send_event("conv.event", data):
                break
    finally:
        stop_event.set()
        runtime.hub.unsubscribe(subscription)
        keepalive_task.cancel()
        watcher_task.cancel()
        await asyncio.gather(keepalive_task, watcher_task, return_exceptions=True)
        try:
            await response.write_eof()
        except Exception:
            pass

    return response


async def _parse_room_members(body: dict[str, Any]) -> list[str] | None:
    members = body.get("members", [])
    if members is None:
        members = []
    if not isinstance(members, list) or any(not isinstance(m, str) for m in members):
        return None
    return list(members)


async def handle_room_create(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    conv_id = body.get("conv_id")
    members = await _parse_room_members(body)
    if not isinstance(conv_id, str) or not conv_id:
        return _invalid_request("conv_id required")
    if members is None:
        return _invalid_request("members must be a list of user_ids")
    try:
        runtime.conversations.create(
            conv_id, session.user_id, members, home_gateway=runtime.gateway_id
        )
    except ValueError:
        return _invalid_request("conversation already exists")
    except LimitExceeded as exc:
        return _limit_exceeded(str(exc))
    return web.json_response({"status": "ok"})


async def handle_conversations_list(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    return web.json_response({"items": runtime.conversations.list_for_user(session.user_id)})


async def handle_room_invite(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    conv_id = body.get("conv_id")
    members = await _parse_room_members(body)
    if not isinstance(conv_id, str) or not conv_id:
        return _invalid_request("conv_id required")
    if members is None:
        return _invalid_request("members must be a list of user_ids")
    try:
        runtime.conversations.invite(conv_id, session.user_id, members)
    except PermissionError:
        return _forbidden("forbidden")
    except RateLimitExceeded as exc:
        return _rate_limited(str(exc))
    except LimitExceeded as exc:
        return _limit_exceeded(str(exc))
    except ValueError:
        return _forbidden("unknown conversation")
    return web.json_response({"status": "ok"})


async def handle_room_remove(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    conv_id = body.get("conv_id")
    members = await _parse_room_members(body)
    if not isinstance(conv_id, str) or not conv_id:
        return _invalid_request("conv_id required")
    if members is None:
        return _invalid_request("members must be a list of user_ids")
    try:
        runtime.conversations.remove(conv_id, session.user_id, members)
    except PermissionError:
        return _forbidden("forbidden")
    except RateLimitExceeded as exc:
        return _rate_limited(str(exc))
    except LimitExceeded as exc:
        return _limit_exceeded(str(exc))
    except ValueError:
        return _forbidden("unknown conversation")
    return web.json_response({"status": "ok"})


async def handle_room_promote(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    conv_id = body.get("conv_id")
    members = await _parse_room_members(body)
    if not isinstance(conv_id, str) or not conv_id:
        return _invalid_request("conv_id required")
    if members is None:
        return _invalid_request("members must be a list of user_ids")
    try:
        runtime.conversations.promote_admin(conv_id, session.user_id, members)
    except PermissionError:
        return _forbidden("forbidden")
    except ValueError:
        return _forbidden("unknown conversation")
    return web.json_response({"status": "ok"})


async def handle_room_demote(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    conv_id = body.get("conv_id")
    members = await _parse_room_members(body)
    if not isinstance(conv_id, str) or not conv_id:
        return _invalid_request("conv_id required")
    if members is None:
        return _invalid_request("members must be a list of user_ids")
    try:
        runtime.conversations.demote_admin(conv_id, session.user_id, members)
    except PermissionError:
        return _forbidden("forbidden")
    except ValueError:
        return _forbidden("unknown conversation")
    return web.json_response({"status": "ok"})


async def handle_social_publish(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    session = _authenticate_request(request)
    if session is None:
        return _unauthorized()

    try:
        body = await request.json()
    except Exception:
        return _invalid_request("malformed json")

    prev_hash = body.get("prev_hash")
    ts_ms = body.get("ts_ms")
    kind = body.get("kind")
    payload = body.get("payload")
    sig_b64 = body.get("sig_b64")

    if prev_hash == "":
        prev_hash = None
    if prev_hash is not None and not isinstance(prev_hash, str):
        return _invalid_request("prev_hash must be a string when provided")
    if not isinstance(ts_ms, int) or ts_ms < 0:
        return _invalid_request("ts_ms must be a non-negative integer")
    if not isinstance(kind, str) or not kind:
        return _invalid_request("kind required")
    if payload is None or not isinstance(payload, dict):
        return _invalid_request("payload must be a JSON object")
    if not isinstance(sig_b64, str) or not sig_b64:
        return _invalid_request("sig_b64 required")

    try:
        event = runtime.social.append(
            user_id=session.user_id,
            prev_hash=prev_hash,
            ts_ms=ts_ms,
            kind=kind,
            payload=payload,
            sig_b64=sig_b64,
        )
    except InvalidSignature:
        return _invalid_request("invalid signature")
    except InvalidChain as exc:
        return _invalid_request(str(exc))
    except TypeError:
        return _invalid_request("payload must be JSON-serializable")

    return _with_no_store(web.json_response(event.to_api_dict()))


async def handle_social_events(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    user_id = request.query.get("user_id")
    if not user_id:
        return _invalid_request("user_id required")

    limit_str = request.query.get("limit")
    limit = 50
    if limit_str is not None:
        try:
            limit = int(limit_str)
        except ValueError:
            return _invalid_request("limit must be an integer")
    if limit <= 0:
        return _invalid_request("limit must be positive")
    limit = min(limit, 200)

    after_hash = request.query.get("after_hash")
    events = runtime.social.list_events(user_id, limit=limit, after_hash=after_hash)
    body = {"events": [event.to_api_dict() for event in events]}

    etag = None
    last_modified_ms = None
    if events:
        etag = f"W/\"{events[-1].event_hash}:{len(events)}\""
        last_modified_ms = events[-1].ts_ms

    response = web.json_response(body)
    return _with_cache(response, etag=etag, last_modified_ms=last_modified_ms)


async def handle_social_profile(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    user_id = request.query.get("user_id")
    if not user_id:
        return _invalid_request("user_id required")

    limit_str = request.query.get("limit")
    latest_posts_limit = 20
    if limit_str is not None:
        try:
            latest_posts_limit = int(limit_str)
        except ValueError:
            return _invalid_request("limit must be an integer")
    if latest_posts_limit <= 0:
        return _invalid_request("limit must be positive")
    latest_posts_limit = min(latest_posts_limit, 100)

    social_events = runtime.social.list_all_events(user_id)
    username_event = latest_event_by_kind(social_events, "username")
    description_event = latest_event_by_kind(social_events, "description")
    avatar_event = latest_event_by_kind(social_events, "avatar")
    banner_event = latest_event_by_kind(social_events, "banner")
    interests_event = latest_event_by_kind(social_events, "interests")

    follow_state: dict[str, tuple[int, str, bool]] = {}
    posts = []
    last_modified_ms = None
    for social_event in social_events:
        last_modified_ms = max(last_modified_ms or 0, social_event.ts_ms)
        payload = decode_payload_json(social_event)
        if social_event.kind == "follow":
            parsed = parse_follow_payload(payload)
            if parsed is None:
                continue
            target_user_id, following = parsed
            current = follow_state.get(target_user_id)
            sort_key = (social_event.ts_ms, social_event.event_hash)
            if current is None or sort_key > (current[0], current[1]):
                follow_state[target_user_id] = (social_event.ts_ms, social_event.event_hash, following)
        if social_event.kind == "post":
            posts.append(social_event)

    friends = sorted([friend for friend, state in follow_state.items() if state[2]])
    posts.sort(key=lambda item: (item.ts_ms, item.event_hash), reverse=True)
    latest_posts = [item.to_api_dict() for item in posts[:latest_posts_limit]]

    def value_or_empty(social_event):
        if social_event is None:
            return ""
        payload = decode_payload_json(social_event)
        return str(payload.get("value", ""))

    profile_body = {
        "user_id": user_id,
        "username": value_or_empty(username_event),
        "description": value_or_empty(description_event),
        "avatar": value_or_empty(avatar_event),
        "banner": value_or_empty(banner_event),
        "interests": value_or_empty(interests_event),
        "friends": friends,
        "latest_posts": latest_posts,
    }

    etag = None
    if social_events:
        etag = f'W/"{social_events[-1].event_hash}:{len(social_events)}:{latest_posts_limit}"'
    response = web.json_response(profile_body)
    return _with_cache(response, etag=etag, last_modified_ms=last_modified_ms)


async def handle_social_feed(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    user_id = request.query.get("user_id")
    if not user_id:
        return _invalid_request("user_id required")

    limit_str = request.query.get("limit")
    limit = 20
    if limit_str is not None:
        try:
            limit = int(limit_str)
        except ValueError:
            return _invalid_request("limit must be an integer")
    if limit <= 0:
        return _invalid_request("limit must be positive")
    limit = min(limit, 100)

    cursor = parse_feed_cursor(request.query.get("cursor"))
    if request.query.get("cursor") and cursor is None:
        return _invalid_request("cursor must be shaped as ts_ms:event_hash")

    user_events = runtime.social.list_all_events(user_id)
    follow_state: dict[str, tuple[int, str, bool]] = {}
    for social_event in user_events:
        if social_event.kind != "follow":
            continue
        payload = decode_payload_json(social_event)
        parsed = parse_follow_payload(payload)
        if parsed is None:
            continue
        target_user_id, following = parsed
        current = follow_state.get(target_user_id)
        sort_key = (social_event.ts_ms, social_event.event_hash)
        if current is None or sort_key > (current[0], current[1]):
            follow_state[target_user_id] = (social_event.ts_ms, social_event.event_hash, following)

    sources = {user_id}
    for friend, state in follow_state.items():
        if state[2]:
            sources.add(friend)

    try:
        posts = runtime.social.list_posts_for_users(sorted(sources), limit=limit, cursor=cursor)
    except CursorNotFound:
        return _invalid_request("cursor not found")
    items = [
        {
            "user_id": item.user_id,
            "event_hash": item.event_hash,
            "ts_ms": item.ts_ms,
            "kind": item.kind,
            "payload": decode_payload_json(item),
        }
        for item in posts
    ]
    next_cursor = ""
    if posts:
        last = posts[-1]
        next_cursor = f"{last.ts_ms}:{last.event_hash}"

    etag = None
    last_modified_ms = None
    if posts:
        etag = f'W/"{posts[0].event_hash}:{next_cursor}:{len(posts)}"'
        last_modified_ms = max(item.ts_ms for item in posts)

    response = web.json_response({"items": items, "next_cursor": next_cursor, "sources": sorted(sources)})
    return _with_cache(response, etag=etag, last_modified_ms=last_modified_ms)


async def handle_gateway_resolve(request: web.Request) -> web.Response:
    runtime: Runtime = request.app[RUNTIME_KEY]
    gateway_id = request.query.get("gateway_id")
    if not gateway_id:
        return _invalid_request("gateway_id required")

    if gateway_id == runtime.gateway_id:
        return web.json_response({"gateway_id": gateway_id, "gateway_url": runtime.gateway_public_url})

    mapped_url = runtime.gateway_directory.get(gateway_id)
    if mapped_url is not None:
        return web.json_response({"gateway_id": gateway_id, "gateway_url": mapped_url})

    return web.json_response({"code": "not_found", "message": "gateway_id not found"}, status=404)


def create_app(
    *,
    ping_interval_s: int = 30,
    ping_miss_limit: int = 2,
    max_msg_size: int = 1_048_576,
    db_path: str | None = None,
    presence: Presence | None = None,
    start_presence_sweeper: bool = True,
    keypackage_fetch_limit_per_min: int = _KEYPACKAGE_FETCH_LIMIT_PER_MIN,
    keypackage_now_func: Callable[[], int] = _now_ms,
    gateway_id: str | None = None,
    gateway_public_url: str | None = None,
    gateway_directory_path: str | None = None,
) -> web.Application:
    backend: SQLiteBackend | None = None
    retention_policy: RetentionPolicy | None = None
    if db_path is not None:
        backend = SQLiteBackend(db_path)
        retention_policy = load_retention_policy_from_env()
        log = SQLiteConversationLog(backend, retention_policy=retention_policy)
        cursors = SQLiteCursorStore(backend)
        sessions: SessionStore = SQLiteSessionStore(backend)
        keypackages = SQLiteKeyPackageStore(backend)
        conversations = SQLiteConversationStore(backend)
        social = SQLiteSocialStore(backend)
    else:
        log = ConversationLog()
        cursors = CursorStore()
        sessions = SessionStore()
        keypackages = InMemoryKeyPackageStore()
        conversations = InMemoryConversationStore()
        social = InMemorySocialStore()

    presence = presence or Presence()
    hub = SubscriptionHub()
    fetch_limiter = FixedWindowRateLimiter(keypackage_fetch_limit_per_min)
    resolved_gateway_id = gateway_id or os.environ.get("GATEWAY_ID") or "gw_local"
    resolved_gateway_public_url = gateway_public_url or os.environ.get("GATEWAY_PUBLIC_URL") or "http://localhost"
    gateway_directory = _load_gateway_directory(
        gateway_directory_path or os.environ.get("GATEWAY_DIRECTORY_PATH")
    )
    runtime = Runtime(
        log=log,
        cursors=cursors,
        hub=hub,
        sessions=sessions,
        keypackages=keypackages,
        backend=backend,
        presence=presence,
        keypackage_fetch_limiter=fetch_limiter,
        now_func=keypackage_now_func,
        conversations=conversations,
        gateway_id=resolved_gateway_id,
        gateway_public_url=resolved_gateway_public_url,
        gateway_directory=gateway_directory,
        social=social,
        retention_policy=retention_policy,
    )
    app = web.Application()
    app[RUNTIME_KEY] = runtime
    app[WS_CONFIG_KEY] = {
        "ping_interval_s": ping_interval_s,
        "ping_miss_limit": ping_miss_limit,
        "max_msg_size": max_msg_size,
    }
    app.router.add_get("/healthz", handle_health)
    app.router.add_post("/v1/keypackages", handle_keypackage_publish)
    app.router.add_post("/v1/keypackages/fetch", handle_keypackage_fetch)
    app.router.add_post("/v1/keypackages/rotate", handle_keypackage_rotate)
    app.router.add_post("/v1/session/start", handle_session_start_http)
    app.router.add_post("/v1/session/resume", handle_session_resume_http)
    app.router.add_post("/v1/inbox", handle_inbox)
    app.router.add_get("/v1/sse", handle_sse)
    app.router.add_post("/v1/presence/lease", handle_presence_lease)
    app.router.add_post("/v1/presence/renew", handle_presence_renew)
    app.router.add_post("/v1/presence/watch", handle_presence_watch)
    app.router.add_post("/v1/presence/unwatch", handle_presence_unwatch)
    app.router.add_post("/v1/presence/block", handle_presence_block)
    app.router.add_post("/v1/presence/unblock", handle_presence_unblock)
    app.router.add_post("/v1/rooms/create", handle_room_create)
    app.router.add_get("/v1/conversations", handle_conversations_list)
    app.router.add_post("/v1/rooms/invite", handle_room_invite)
    app.router.add_post("/v1/rooms/remove", handle_room_remove)
    app.router.add_post("/v1/rooms/promote", handle_room_promote)
    app.router.add_post("/v1/rooms/demote", handle_room_demote)
    app.router.add_post("/v1/social/events", handle_social_publish)
    app.router.add_get("/v1/social/events", handle_social_events)
    app.router.add_get("/v1/social/profile", handle_social_profile)
    app.router.add_get("/v1/social/feed", handle_social_feed)
    app.router.add_get("/v1/gateways/resolve", handle_gateway_resolve)
    app.router.add_get("/v1/ws", websocket_handler)

    async def retention_sweeper(app_: web.Application) -> None:
        runtime_ = app_[RUNTIME_KEY]
        policy = runtime_.retention_policy
        if policy is None or not policy.enabled or not isinstance(runtime_.log, SQLiteConversationLog):
            return
        interval = policy.sweep_interval_s
        while True:
            try:
                await asyncio.sleep(interval)
                now_ms = runtime_.now_func()
                for conv_id in runtime_.log.list_conversations():
                    runtime_.log.prune_conv(
                        conv_id,
                        policy,
                        now_ms,
                        _sqlite_active_min_next_seq(runtime_, conv_id, now_ms),
                    )
            except asyncio.CancelledError:
                return

    async def start_retention(_: web.Application) -> None:
        if runtime.retention_policy is None or not runtime.retention_policy.enabled:
            return
        if not isinstance(runtime.log, SQLiteConversationLog):
            return
        runtime.retention_task = asyncio.create_task(retention_sweeper(app))

    async def stop_retention(_: web.Application) -> None:
        if runtime.retention_task is None:
            return
        runtime.retention_task.cancel()
        try:
            await runtime.retention_task
        except asyncio.CancelledError:
            pass
        runtime.retention_task = None

    app.on_startup.append(start_retention)
    app.on_cleanup.append(stop_retention)

    if backend is not None:
        async def close_db(_: web.Application) -> None:
            backend.close()

        app.on_cleanup.append(close_db)

    async def start_presence(_: web.Application) -> None:
        if start_presence_sweeper:
            presence.start_sweeper()

    async def stop_presence(_: web.Application) -> None:
        await presence.stop_sweeper()

    app.on_startup.append(start_presence)
    app.on_cleanup.append(stop_presence)
    return app


def _error_frame(
    code: str,
    message: str,
    *,
    request_id: str | None = None,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if extra_body:
        body.update(extra_body)
    return {"v": 1, "t": "error", "id": request_id, "body": body}


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    runtime: Runtime = request.app[RUNTIME_KEY]
    ws_config: WsConfig = request.app[WS_CONFIG_KEY]

    ws = web.WebSocketResponse(max_msg_size=ws_config["max_msg_size"])
    await ws.prepare(request)

    last_activity = asyncio.get_event_loop().time()
    missed_heartbeats = 0
    outbound: asyncio.Queue[Union[ConversationEvent, dict, None]] = asyncio.Queue(maxsize=1000)
    subscriptions: List[Subscription] = []
    session: Session | None = None
    closed = False

    async def close_with_error(message: str) -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        await ws.close(code=1011, message=message.encode("utf-8"))

    def mark_activity() -> None:
        nonlocal last_activity, missed_heartbeats
        last_activity = asyncio.get_event_loop().time()
        missed_heartbeats = 0

    def enqueue_event(event: ConversationEvent | dict) -> None:
        try:
            outbound.put_nowait(event)
        except asyncio.QueueFull:
            asyncio.create_task(close_with_error("backpressure"))

    async def writer() -> None:
        try:
            while True:
                event = await outbound.get()
                if event is None:
                    break
                if isinstance(event, ConversationEvent):
                    await ws.send_json(
                        {
                            "v": 1,
                            "t": "conv.event",
                            "body": {
                                "conv_id": event.conv_id,
                                "seq": event.seq,
                                "msg_id": event.msg_id,
                                "env": event.envelope_b64,
                                "sender_device_id": event.sender_device_id,
                                **_routing_metadata(runtime, event.conv_id),
                            },
                        }
                    )
                else:
                    await ws.send_json(event)
        except asyncio.CancelledError:
            return

    async def heartbeat() -> None:
        nonlocal missed_heartbeats
        try:
            while True:
                await asyncio.sleep(ws_config["ping_interval_s"])
                if ws.closed:
                    return
                now = asyncio.get_event_loop().time()
                if now - last_activity >= ws_config["ping_interval_s"]:
                    await ws.send_json({"v": 1, "t": "ping"})
                    missed_heartbeats += 1
                    if missed_heartbeats > ws_config["ping_miss_limit"]:
                        await ws.close(code=1001, message=b"heartbeat timeout")
                        return
        except asyncio.CancelledError:
            return

    writer_task = asyncio.create_task(writer())
    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        first_msg = await ws.receive()
        if first_msg.type != WSMsgType.TEXT:
            await ws.close(code=1002, message=b"invalid handshake")
            return ws
        try:
            payload = first_msg.json()
        except Exception:
            await ws.close(code=1002, message=b"invalid json")
            return ws

        if payload.get("v") != 1:
            await ws.send_json(_error_frame("invalid_request", "unsupported version", request_id=payload.get("id")))
            await ws.close()
            return ws

        t = payload.get("t")
        body = payload.get("body") or {}

        if t == "session.start":
            parsed, error = _validate_session_start_body(body)
            if error:
                await ws.send_json(
                    _error_frame("invalid_request", error, request_id=payload.get("id"))
                )
                await ws.close()
                return ws
            assert parsed is not None
            user_id, device_id = parsed
            session = runtime.sessions.create(user_id, device_id)
        elif t == "session.resume":
            resume_token, error = _validate_session_resume_body(body)
            if error:
                await ws.send_json(
                    _error_frame("invalid_request", error, request_id=payload.get("id"))
                )
                await ws.close()
                return ws
            assert resume_token is not None
            session = runtime.sessions.consume_resume(resume_token)
            if session is None:
                await ws.send_json(
                    _error_frame("resume_failed", "resume token invalid or expired", request_id=payload.get("id"))
                )
                await ws.close()
                return ws
        else:
            await ws.send_json(_error_frame("invalid_request", "first frame must start session", request_id=payload.get("id")))
            await ws.close()
            return ws

        mark_activity()
        device_id = session.device_id
        ready_frame = {
            "v": 1,
            "t": "session.ready",
            "id": payload.get("id"),
            "body": _session_ready_body(runtime, session),
        }
        await ws.send_json(ready_frame)

        runtime.presence.register_callback(session.user_id, device_id, enqueue_event)

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    frame = msg.json()
                except Exception:
                    await ws.send_json(_error_frame("invalid_request", "malformed json"))
                    continue

                mark_activity()
                if frame.get("v") != 1:
                    await ws.send_json(_error_frame("invalid_request", "unsupported version", request_id=frame.get("id")))
                    continue

                frame_type = frame.get("t")
                body = frame.get("body") or {}

                if frame_type == "ping":
                    await ws.send_json({"v": 1, "t": "pong", "id": frame.get("id")})
                elif frame_type == "pong":
                    continue
                elif frame_type == "conv.subscribe":
                    conv_id = body.get("conv_id")
                    if not conv_id:
                        await ws.send_json(_error_frame("invalid_request", "conv_id required", request_id=frame.get("id")))
                        continue
                    if not runtime.conversations.is_known(conv_id) or not runtime.conversations.is_member(
                        conv_id, session.user_id
                    ):
                        await ws.send_json(
                            _error_frame("forbidden", "not a member", request_id=frame.get("id"))
                        )
                        continue
                    from_seq = body.get("from_seq")
                    if from_seq is None:
                        after_seq = body.get("after_seq")
                        if after_seq is not None:
                            from_seq = after_seq + 1
                        else:
                            from_seq = runtime.cursors.next_seq(session.device_id, conv_id)
                    try:
                        events = runtime.log.list_from(conv_id, from_seq, limit=1000)
                    except ReplayWindowExceeded as exc:
                        await ws.send_json(
                            _error_frame(
                                "replay_window_exceeded",
                                f"requested_from_seq={exc.requested_from_seq} earliest_seq={exc.earliest_seq}",
                                request_id=frame.get("id"),
                                extra_body={
                                    "requested_from_seq": exc.requested_from_seq,
                                    "earliest_seq": exc.earliest_seq,
                                    "latest_seq": exc.latest_seq,
                                },
                            )
                        )
                        continue

                    buffered_events: List[ConversationEvent] = []
                    buffering = True

                    revoked = False
                    error_sent = False
                    subscription: Subscription | None = None

                    def stop_subscription() -> None:
                        nonlocal revoked, error_sent
                        if revoked:
                            return
                        revoked = True
                        if subscription is not None:
                            runtime.hub.unsubscribe(subscription)
                        if not error_sent:
                            enqueue_event(
                                {
                                    "v": 1,
                                    "t": "error",
                                    "body": {"code": "forbidden", "message": "membership revoked"},
                                }
                            )
                            error_sent = True

                    def guarded_enqueue(event: ConversationEvent) -> None:
                        if revoked:
                            return
                        if not runtime.conversations.is_member(event.conv_id, session.user_id):
                            stop_subscription()
                            return
                        enqueue_event(event)

                    def buffering_enqueue(event: ConversationEvent) -> None:
                        nonlocal buffering
                        if revoked:
                            return
                        if buffering:
                            buffered_events.append(event)
                            return
                        guarded_enqueue(event)

                    subscription = runtime.hub.subscribe(session.device_id, conv_id, buffering_enqueue)
                    subscriptions.append(subscription)

                    for event in events:
                        guarded_enqueue(event)

                    buffering = False
                    for event in buffered_events:
                        guarded_enqueue(event)
                elif frame_type == "conv.send":
                    seq, _, error = _process_conv_send(runtime, session, body)
                    if error:
                        await ws.send_json(_error_frame(error[0], error[1], request_id=frame.get("id")))
                        continue
                    assert seq is not None
                    await ws.send_json(
                        {
                            "v": 1,
                            "t": "conv.acked",
                            "id": frame.get("id"),
                            "body": {
                                "conv_id": body.get("conv_id"),
                                "msg_id": body.get("msg_id"),
                                "seq": seq,
                                **_routing_metadata(runtime, body.get("conv_id")),
                            },
                        }
                    )
                elif frame_type == "conv.ack":
                    error = _process_conv_ack(runtime, session, body)
                    if error:
                        await ws.send_json(
                            _error_frame(error[0], error[1], request_id=frame.get("id"))
                        )
                        continue
                else:
                    await ws.send_json(
                        _error_frame("invalid_request", "unknown frame type", request_id=frame.get("id"))
                    )
            elif msg.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                break
            else:
                await ws.close(code=1003, message=b"unsupported frame type")
                break
    finally:
        heartbeat_task.cancel()
        writer_task.cancel()
        for subscription in subscriptions:
            runtime.hub.unsubscribe(subscription)
        if session is not None:
            runtime.presence.unregister_callback(session.device_id)
        if not outbound.empty():
            try:
                outbound.put_nowait(None)
            except asyncio.QueueFull:
                pass
        else:
            outbound.put_nowait(None)
        await asyncio.gather(heartbeat_task, writer_task, return_exceptions=True)

    return ws
