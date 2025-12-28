from __future__ import annotations

import asyncio
from typing import Any

from .web import Application, Request, WebSocketResponse


class TestServer:
    def __init__(self, app: Application) -> None:
        self.app = app

    async def start_server(self) -> None:
        return None

    def make_url(self, path: str) -> str:
        return path

    async def close(self) -> None:
        return None


class TestClient:
    def __init__(self, server: TestServer) -> None:
        self.server = server
        self._tasks: list[asyncio.Task[Any]] = []

    async def start_server(self) -> None:
        return None

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def ws_connect(self, path: str) -> WebSocketResponse:
        handler = self.server.app.router.resolve(path)
        client_ws = WebSocketResponse()
        WebSocketResponse._pending_peers.append(client_ws)
        request = Request(app=self.server.app, path=path)
        task = asyncio.create_task(handler(request))
        self._tasks.append(task)
        await client_ws._peer_ready.wait()
        return client_ws
