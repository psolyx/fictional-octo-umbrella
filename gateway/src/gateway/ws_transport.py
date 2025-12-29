from __future__ import annotations

import asyncio
import importlib
import secrets
from typing import Any, List, Union

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is not None:  # pragma: no cover - exercised in CI with deps
    from aiohttp import WSMsgType, web
else:  # pragma: no cover - offline fallback
    from gateway.aiohttp_stub import WSMsgType, web

from .cursors import CursorStore
from .hub import Subscription, SubscriptionHub
# In-memory conversation log implementation used when SQLite durability is disabled.
from .keypackages import InMemoryKeyPackageStore, SQLiteKeyPackageStore
from .log import ConversationEvent, ConversationLog
from .presence import LimitExceeded, Presence, RateLimitExceeded
from .sqlite_backend import SQLiteBackend
from .sqlite_cursors import SQLiteCursorStore
from .sqlite_log import SQLiteConversationLog
from .sqlite_sessions import Session, SQLiteSessionStore, _now_ms


class SessionStore:
    """Tracks active sessions keyed by both session and resume tokens."""

    def __init__(self, ttl_ms: int = 60 * 60 * 1000) -> None:
        self._ttl_ms = ttl_ms
        self._by_session: dict[str, Session] = {}
        self._by_resume: dict[str, Session] = {}

    def create(self, device_id: str) -> Session:
        now_ms = _now_ms()
        session = Session(
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
    ) -> None:
        self.log = log
        self.cursors = cursors
        self.hub = hub
        self.sessions = sessions
        self.keypackages = keypackages
        self.backend = backend
        self.presence = presence


async def handle_health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def _unauthorized() -> web.Response:
    return web.json_response({"code": "unauthorized", "message": "invalid session_token"}, status=401)


def _invalid_request(message: str) -> web.Response:
    return web.json_response({"code": "invalid_request", "message": message}, status=400)


def _rate_limited(message: str) -> web.Response:
    return web.json_response({"code": "rate_limited", "message": message}, status=429)


def _limit_exceeded(message: str) -> web.Response:
    return web.json_response({"code": "limit_exceeded", "message": message}, status=429)


def _with_no_store(response: web.Response) -> web.Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _authenticate_request(request: web.Request) -> Session | None:
    runtime: Runtime = request.app["runtime"]
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    session_token = auth_header[len("Bearer ") :].strip()
    return runtime.sessions.get_by_session(session_token)


async def handle_keypackage_publish(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]
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

    runtime.keypackages.publish(device_id, keypackages)
    return web.json_response({"status": "ok"})


async def handle_keypackage_fetch(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]
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

    # Until Polycentric user identity is integrated, user_id is treated as a device namespace key.
    keypackages = runtime.keypackages.fetch(user_id, count)
    return web.json_response({"keypackages": keypackages})


async def handle_keypackage_rotate(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]
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
    runtime.keypackages.rotate(device_id, bool(revoke), replacement)
    return web.json_response({"status": "ok"})


def _no_store_response(data: dict[str, Any], status: int = 200) -> web.Response:
    response = web.json_response(data, status=status)
    return _with_no_store(response)


async def handle_presence_lease(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]
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
        expires_at = runtime.presence.lease(device_id, ttl_seconds, invisible=invisible)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    return _no_store_response({"status": "ok", "expires_at": expires_at})


async def handle_presence_renew(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]
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
        expires_at = runtime.presence.renew(device_id, ttl_seconds, invisible=invisible)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    return _no_store_response({"status": "ok", "expires_at": expires_at})


async def handle_presence_watch(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]
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
        runtime.presence.watch(session.device_id, contacts)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    except LimitExceeded as exc:
        return _with_no_store(_limit_exceeded(str(exc)))
    return _no_store_response({"status": "ok", "watching": runtime.presence.watchlist_size(session.device_id)})


async def handle_presence_unwatch(request: web.Request) -> web.Response:
    runtime: Runtime = request.app["runtime"]
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
        runtime.presence.unwatch(session.device_id, contacts)
    except RateLimitExceeded as exc:
        return _with_no_store(_rate_limited(str(exc)))
    return _no_store_response({"status": "ok", "watching": runtime.presence.watchlist_size(session.device_id)})


def create_app(
    *,
    ping_interval_s: int = 30,
    ping_miss_limit: int = 2,
    max_msg_size: int = 1_048_576,
    db_path: str | None = None,
    presence: Presence | None = None,
    start_presence_sweeper: bool = True,
) -> web.Application:
    backend: SQLiteBackend | None = None
    if db_path is not None:
        backend = SQLiteBackend(db_path)
        log = SQLiteConversationLog(backend)
        cursors = SQLiteCursorStore(backend)
        sessions: SessionStore = SQLiteSessionStore(backend)
        keypackages = SQLiteKeyPackageStore(backend)
    else:
        log = ConversationLog()
        cursors = CursorStore()
        sessions = SessionStore()
        keypackages = InMemoryKeyPackageStore()

    presence = presence or Presence()
    hub = SubscriptionHub()
    runtime = Runtime(
        log=log,
        cursors=cursors,
        hub=hub,
        sessions=sessions,
        keypackages=keypackages,
        backend=backend,
        presence=presence,
    )
    app = web.Application()
    app["runtime"] = runtime
    app["ws_config"] = {
        "ping_interval_s": ping_interval_s,
        "ping_miss_limit": ping_miss_limit,
        "max_msg_size": max_msg_size,
    }
    app.router.add_get("/healthz", handle_health)
    app.router.add_post("/v1/keypackages", handle_keypackage_publish)
    app.router.add_post("/v1/keypackages/fetch", handle_keypackage_fetch)
    app.router.add_post("/v1/keypackages/rotate", handle_keypackage_rotate)
    app.router.add_post("/v1/presence/lease", handle_presence_lease)
    app.router.add_post("/v1/presence/renew", handle_presence_renew)
    app.router.add_post("/v1/presence/watch", handle_presence_watch)
    app.router.add_post("/v1/presence/unwatch", handle_presence_unwatch)
    app.router.add_get("/v1/ws", websocket_handler)
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


def _error_frame(code: str, message: str, *, request_id: str | None = None) -> dict[str, Any]:
    return {"v": 1, "t": "error", "id": request_id, "body": {"code": code, "message": message}}


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    runtime: Runtime = request.app["runtime"]
    ws_config: dict[str, Any] = request.app["ws_config"]

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
            auth_token = body.get("auth_token")
            device_id = body.get("device_id")
            if not auth_token or not device_id:
                await ws.send_json(
                    _error_frame("invalid_request", "auth_token and device_id required", request_id=payload.get("id"))
                )
                await ws.close()
                return ws
            session = runtime.sessions.create(device_id)
        elif t == "session.resume":
            resume_token = body.get("resume_token")
            if not resume_token:
                await ws.send_json(
                    _error_frame("invalid_request", "resume_token required", request_id=payload.get("id"))
                )
                await ws.close()
                return ws
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
        cursor_rows = runtime.cursors.list_cursors(device_id)
        cursors = [{"conv_id": conv_id, "next_seq": next_seq} for conv_id, next_seq in cursor_rows]
        ready_frame = {
            "v": 1,
            "t": "session.ready",
            "id": payload.get("id"),
            "body": {
                "session_token": session.session_token,
                "resume_token": session.resume_token,
                "expires_at": session.expires_at_ms,
                "cursors": cursors,
            },
        }
        await ws.send_json(ready_frame)

        runtime.presence.register_callback(device_id, enqueue_event)

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
                    from_seq = body.get("from_seq")
                    if from_seq is None:
                        after_seq = body.get("after_seq")
                        if after_seq is not None:
                            from_seq = after_seq + 1
                        else:
                            from_seq = runtime.cursors.next_seq(session.device_id, conv_id)
                    events = runtime.log.list_from(conv_id, from_seq, limit=1000)

                    buffered_events: List[ConversationEvent] = []
                    buffering = True

                    def buffering_enqueue(event: ConversationEvent) -> None:
                        nonlocal buffering
                        if buffering:
                            buffered_events.append(event)
                            return
                        enqueue_event(event)

                    subscription = runtime.hub.subscribe(session.device_id, conv_id, buffering_enqueue)
                    subscriptions.append(subscription)

                    for event in events:
                        enqueue_event(event)

                    buffering = False
                    for event in buffered_events:
                        enqueue_event(event)
                elif frame_type == "conv.send":
                    conv_id = body.get("conv_id")
                    msg_id = body.get("msg_id")
                    env = body.get("env")
                    if not conv_id or not msg_id or env is None:
                        await ws.send_json(
                            _error_frame("invalid_request", "conv_id, msg_id, env required", request_id=frame.get("id"))
                        )
                        continue
                    seq, event, created = runtime.log.append(
                        conv_id, msg_id, env, session.device_id, body.get("ts") or _now_ms()
                    )
                    if created:
                        runtime.hub.broadcast(event)
                    await ws.send_json(
                        {
                            "v": 1,
                            "t": "conv.acked",
                            "id": frame.get("id"),
                            "body": {"conv_id": conv_id, "msg_id": msg_id, "seq": seq},
                        }
                    )
                elif frame_type == "conv.ack":
                    conv_id = body.get("conv_id")
                    seq = body.get("seq")
                    if not conv_id or seq is None:
                        await ws.send_json(
                            _error_frame("invalid_request", "conv_id and seq required", request_id=frame.get("id"))
                        )
                        continue
                    runtime.cursors.ack(session.device_id, conv_id, int(seq))
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
