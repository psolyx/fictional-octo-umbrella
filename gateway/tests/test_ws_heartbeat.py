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

            ping = await asyncio.wait_for(ws.receive_json(), timeout=2)
            self.assertEqual(ping["t"], "ping")

            close_seen = False
            while not close_seen:
                msg = await asyncio.wait_for(ws.receive(), timeout=2)
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

            await ws.send_json({"v": 1, "t": "ping", "id": "c1"})
            pong1 = await asyncio.wait_for(ws.receive_json(), timeout=1)
            self.assertEqual(pong1["t"], "pong")
            self.assertEqual(pong1["id"], "c1")

            await ws.send_json({"v": 1, "t": "ping", "id": "c2"})
            pong2 = await asyncio.wait_for(ws.receive_json(), timeout=1)
            self.assertEqual(pong2["t"], "pong")
            self.assertEqual(pong2["id"], "c2")

            try:
                server_ping = await asyncio.wait_for(ws.receive_json(), timeout=1.5)
            except asyncio.TimeoutError:
                server_ping = None

            if server_ping and server_ping.get("t") == "ping":
                await ws.send_json({"v": 1, "t": "pong", "id": server_ping.get("id")})

            await ws.send_json({"v": 1, "t": "ping", "id": "c3"})
            pong3 = await asyncio.wait_for(ws.receive_json(), timeout=1)
            self.assertEqual(pong3["t"], "pong")
            self.assertEqual(pong3["id"], "c3")

            self.assertFalse(ws.closed)
        finally:
            await client.close()
            await server.close()


if __name__ == "__main__":
    unittest.main()
