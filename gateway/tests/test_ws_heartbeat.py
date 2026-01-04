import asyncio
import importlib
import importlib.metadata
import unittest

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway WS tests")

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway WS tests, found {_installed_aiohttp}"
    )

from gateway.ws_transport import create_app


class WsHeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def _start_client(self, *, ping_interval_s: int, ping_miss_limit: int) -> tuple[TestClient, TestServer]:
        app = create_app(ping_interval_s=ping_interval_s, ping_miss_limit=ping_miss_limit)
        server = TestServer(app)
        await server.start_server()
        client = TestClient(server)
        await client.start_server()
        return client, server

    async def _start_session(self, client: TestClient):
        ws = await client.ws_connect("/v1/ws")
        await ws.send_json(
            {
                "v": 1,
                "t": "session.start",
                "id": "start1",
                "body": {"auth_token": "t", "device_id": "d1"},
            }
        )
        ready = await ws.receive_json()
        return ws, ready

    async def test_idle_ping_triggers_timeout_close(self):
        client, server = await self._start_client(ping_interval_s=1, ping_miss_limit=0)
        try:
            ws, _ = await self._start_session(client)

            loop = asyncio.get_running_loop()
            ping_deadline = loop.time() + 8
            ping_seen = False

            while not ping_seen:
                remaining = ping_deadline - loop.time()
                if remaining <= 0:
                    self.fail("Timed out waiting for server ping")

                msg = await ws.receive(timeout=remaining)
                if msg.type == WSMsgType.TEXT:
                    payload = msg.json()
                    if payload.get("t") == "ping":
                        ping_seen = True
                        break
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                    self.fail("Connection closed before ping was observed")

            close_deadline = loop.time() + 8
            close_seen = ws.closed

            while not close_seen:
                remaining = close_deadline - loop.time()
                if remaining <= 0:
                    self.fail("Timed out waiting for server to close idle connection")

                msg = await ws.receive(timeout=remaining)
                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                    close_seen = True
                    break

            self.assertTrue(ws.closed)
            self.assertTrue(close_seen)
        finally:
            await client.close()
            await server.close()

    async def test_client_ping_receives_pong_and_stays_open(self):
        client, server = await self._start_client(ping_interval_s=1, ping_miss_limit=1)
        try:
            ws, _ = await self._start_session(client)

            async def assert_pong_for_client_ping(ping_id: str, *, deadline: float):
                await ws.send_json({"v": 1, "t": "ping", "id": ping_id})
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        self.fail(f"Timed out waiting for pong {ping_id}")

                    msg = await ws.receive(timeout=remaining)
                    if msg.type == WSMsgType.TEXT:
                        payload = msg.json()
                        if payload.get("t") == "ping":
                            await ws.send_json({"v": 1, "t": "pong", "id": payload.get("id")})
                            continue
                        if payload.get("t") == "pong" and payload.get("id") == ping_id:
                            return
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                        self.fail("Connection closed while waiting for pong")

            loop = asyncio.get_running_loop()
            await assert_pong_for_client_ping("c1", deadline=loop.time() + 5)
            await assert_pong_for_client_ping("c2", deadline=loop.time() + 5)
            await assert_pong_for_client_ping("c3", deadline=loop.time() + 5)

            self.assertFalse(ws.closed)
        finally:
            await client.close()
            await server.close()


if __name__ == "__main__":
    unittest.main()
