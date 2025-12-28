from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict


class WSMsgType(Enum):
    TEXT = 1
    CLOSE = 2
    CLOSED = 3
    ERROR = 4


class WSMessage:
    def __init__(self, msg_type: WSMsgType, data: Any = None) -> None:
        self.type = msg_type
        self.data = data

    def json(self) -> Any:
        if isinstance(self.data, str):
            return json.loads(self.data)
        return self.data


class Response:
    def __init__(self, text: str = "") -> None:
        self.text = text


class Request:
    def __init__(self, app: "Application", path: str) -> None:
        self.app = app
        self.path = path


class Router:
    def __init__(self) -> None:
        self._routes: Dict[str, Callable[[Request], Awaitable[Any]]] = {}

    def add_get(self, path: str, handler: Callable[[Request], Awaitable[Any]]) -> None:
        self._routes[path] = handler

    def resolve(self, path: str) -> Callable[[Request], Awaitable[Any]]:
        return self._routes[path]


class Application(dict):
    def __init__(self) -> None:
        super().__init__()
        self.router = Router()


class WebSocketResponse:
    _pending_peers: list["WebSocketResponse"] = []

    def __init__(self, *, max_msg_size: int | None = None) -> None:
        self.max_msg_size = max_msg_size
        self._incoming: asyncio.Queue[WSMessage] = asyncio.Queue()
        self._peer: WebSocketResponse | None = None
        self._closed = False
        self._peer_ready = asyncio.Event()
        if WebSocketResponse._pending_peers:
            peer = WebSocketResponse._pending_peers.pop()
            self._set_peer(peer)
            peer._set_peer(self)

    def _set_peer(self, peer: "WebSocketResponse") -> None:
        self._peer = peer
        self._peer_ready.set()

    async def prepare(self, request: Request) -> "WebSocketResponse":
        self._request = request
        return self

    async def receive(self) -> WSMessage:
        return await self._incoming.get()

    async def receive_json(self) -> Any:
        msg = await self.receive()
        return msg.json()

    async def send_json(self, payload: Any) -> None:
        if self._peer is None:
            await self._peer_ready.wait()
        await self._peer._incoming.put(WSMessage(WSMsgType.TEXT, json.dumps(payload)))

    async def close(self, code: int | None = None, message: bytes | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        if self._peer is not None:
            await self._peer._incoming.put(WSMessage(WSMsgType.CLOSED))
            self._peer._peer_ready.set()

    def __aiter__(self) -> "WebSocketResponse":
        return self

    async def __anext__(self) -> WSMessage:
        msg = await self.receive()
        if msg.type in {WSMsgType.CLOSED, WSMsgType.CLOSE}:
            raise StopAsyncIteration
        return msg

    @property
    def closed(self) -> bool:
        return self._closed


class web:
    Application = Application
    Request = Request
    Response = Response
    WebSocketResponse = WebSocketResponse


async def run_app(app: Application, *, host: str = "127.0.0.1", port: int = 8080) -> None:
    raise RuntimeError("aiohttp stub cannot run a real network server; install aiohttp for serving")
