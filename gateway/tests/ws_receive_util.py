import asyncio
import json
from typing import Any, Callable

from aiohttp import WSMessage, web


async def _receive_with_deadline(ws: web.WebSocketResponse, deadline: float) -> WSMessage:
    loop = asyncio.get_running_loop()
    remaining = deadline - loop.time()
    if remaining <= 0:
        raise asyncio.TimeoutError("Timed out waiting for websocket message")
    return await ws.receive(timeout=remaining)


async def _handle_control_message(ws: web.WebSocketResponse, msg: WSMessage) -> bool:
    if msg.type == web.WSMsgType.PING:
        await ws.pong()
        return True
    if msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSING, web.WSMsgType.CLOSED):
        raise AssertionError("WebSocket closed while waiting for message")
    if msg.type == web.WSMsgType.ERROR:
        raise AssertionError(f"WebSocket error while waiting for message: {ws.exception()}")
    return False


async def _parse_json_payload(ws: web.WebSocketResponse, msg: WSMessage) -> Any | None:
    if msg.type != web.WSMsgType.TEXT:
        return None
    try:
        payload = json.loads(msg.data)
    except ValueError:
        return None
    if isinstance(payload, dict) and payload.get("t") == "ping":
        await ws.send_json({"v": 1, "t": "pong", "id": payload.get("id")})
        return None
    return payload


async def recv_json_until(
    ws: web.WebSocketResponse,
    *,
    deadline: float,
    predicate: Callable[[Any], bool],
) -> Any:
    while True:
        msg = await _receive_with_deadline(ws, deadline)
        if await _handle_control_message(ws, msg):
            continue
        payload = await _parse_json_payload(ws, msg)
        if payload is None:
            continue
        if predicate(payload):
            return payload


async def assert_no_app_messages(ws: web.WebSocketResponse, *, timeout: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            msg = await _receive_with_deadline(ws, deadline)
        except asyncio.TimeoutError:
            return
        if await _handle_control_message(ws, msg):
            continue
        payload = await _parse_json_payload(ws, msg)
        if payload is None:
            continue
        raise AssertionError(f"Unexpected websocket message: {payload}")
