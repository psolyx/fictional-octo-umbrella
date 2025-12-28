from __future__ import annotations

import asyncio
import importlib
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, List

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is not None:  # pragma: no cover - exercised in CI with deps
    from aiohttp import WSMsgType, web
else:  # pragma: no cover - offline fallback
    from gateway.aiohttp_stub import WSMsgType, web

from .cursors import CursorStore
from .hub import Subscription, SubscriptionHub
from .log import ConversationEvent, ConversationLog


@dataclass
class Session:
    device_id: str
    session_token: str
    resume_token: str
    expires_at_ms: int


class SessionStore:
    """Tracks active sessions keyed by both session and resume tokens."""

    def __init__(self, ttl_ms: int = 60 * 60 * 1000) -> None:
        self._ttl_ms = ttl_ms
        self._by_session: Dict[str, Session] = {}
        self._by_resume: Dict[str, Session] = {}

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

    def get_by_resume(self, resume_token: str) -> Session | None:
        session = self._by_resume.get(resume_token)
        if session is None:
            return None
        if session.expires_at_ms <= _now_ms():
            self.invalidate(session)
            return None
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
    def __init__(self) -> None:
        self.log = ConversationLog()
        self.cursors = CursorStore()
        self.hub = SubscriptionHub()
        self.sessions = SessionStore()


async def handle_health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_app(
    *, ping_interval_s: int = 30, ping_miss_limit: int = 2, max_msg_size: int = 1_048_576
) -> web.Application:
    runtime = Runtime()
    app = web.Application()
    app["runtime"] = runtime
    app["ws_config"] = {
        "ping_interval_s": ping_interval_s,
        "ping_miss_limit": ping_miss_limit,
        "max_msg_size": max_msg_size,
    }
    app.router.add_get("/healthz", handle_health)
    app.router.add_get("/v1/ws", websocket_handler)
    return app


def _now_ms() -> int:
    return int(time.time() * 1000)


def _error_frame(code: str, message: str, *, request_id: str | None = None) -> dict[str, Any]:
    return {"v": 1, "t": "error", "id": request_id, "body": {"code": code, "message": message}}


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    runtime: Runtime = request.app["runtime"]
    ws_config: dict[str, Any] = request.app["ws_config"]

    ws = web.WebSocketResponse(max_msg_size=ws_config["max_msg_size"])
    await ws.prepare(request)

    last_activity = asyncio.get_event_loop().time()
    missed_heartbeats = 0
    outbound: asyncio.Queue[ConversationEvent | None] = asyncio.Queue(maxsize=1000)
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

    def enqueue_event(event: ConversationEvent) -> None:
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
            session = runtime.sessions.get_by_resume(resume_token)
            if session is None:
                await ws.send_json(
                    _error_frame("resume_failed", "resume token invalid or expired", request_id=payload.get("id"))
                )
                await ws.close()
                return ws
            session = runtime.sessions.rotate_resume(session)
        else:
            await ws.send_json(_error_frame("invalid_request", "first frame must start session", request_id=payload.get("id")))
            await ws.close()
            return ws

        mark_activity()
        await ws.send_json(
            {
                "v": 1,
                "t": "session.ready",
                "id": payload.get("id"),
                "body": {
                    "session_token": session.session_token,
                    "resume_token": session.resume_token,
                    "expires_at": session.expires_at_ms,
                    "cursors": [
                        {"conv_id": conv_id, "next_seq": next_seq}
                        for conv_id, next_seq in runtime.cursors.list_cursors(session.device_id)
                    ],
                },
            }
        )

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

                    subscription = runtime.hub.subscribe(session.device_id, conv_id, enqueue_event)
                    subscriptions.append(subscription)

                    for event in events:
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
                    await ws.send_json(
                        {
                            "v": 1,
                            "t": "conv.acked",
                            "id": frame.get("id"),
                            "body": {"conv_id": conv_id, "msg_id": msg_id, "seq": seq},
                        }
                    )
                    if created:
                        runtime.hub.broadcast(event)
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
        if not outbound.empty():
            try:
                outbound.put_nowait(None)
            except asyncio.QueueFull:
                pass
        else:
            outbound.put_nowait(None)
        await asyncio.gather(heartbeat_task, writer_task, return_exceptions=True)

    return ws
