import asyncio
import importlib
import os
import tempfile
import unittest

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway WS tests")

from aiohttp.test_utils import TestClient, TestServer

from gateway.ws_transport import create_app


class WsTransportSQLiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "gateway.db")
        self._servers: list[tuple[TestServer, TestClient]] = []

    async def asyncTearDown(self):
        for server, client in self._servers:
            await client.close()
            await server.close()
        self.tmpdir.cleanup()

    async def _start_runtime(self) -> TestClient:
        app = create_app(ping_interval_s=3600, db_path=self.db_path)
        server = TestServer(app)
        await server.start_server()
        client = TestClient(server)
        await client.start_server()
        self._servers.append((server, client))
        return client

    async def test_resume_persists_cursors_and_sessions(self):
        client = await self._start_runtime()
        ws = await client.ws_connect("/v1/ws")
        await ws.send_json(
            {"v": 1, "t": "session.start", "id": "start1", "body": {"auth_token": "t", "device_id": "d1"}}
        )
        ready = await ws.receive_json()
        self.assertEqual("session.ready", ready["t"])
        self.assertIn("resume_token", ready["body"])
        resume_token = ready["body"]["resume_token"]

        await ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})
        await ws.send_json(
            {
                "v": 1,
                "t": "conv.send",
                "id": "send1",
                "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW4=", "ts": 1},
            }
        )
        await ws.receive_json()  # ack
        await ws.receive_json()  # event
        await ws.send_json({"v": 1, "t": "conv.ack", "body": {"conv_id": "c1", "seq": 1}})
        await ws.close()

        await self._servers[0][1].close()
        await self._servers[0][0].close()
        self._servers.clear()

        client2 = await self._start_runtime()
        ws2 = await client2.ws_connect("/v1/ws")
        await ws2.send_json({"v": 1, "t": "session.resume", "id": "resume1", "body": {"resume_token": resume_token}})
        ready2 = await ws2.receive_json()
        self.assertEqual([{"conv_id": "c1", "next_seq": 2}], ready2["body"]["cursors"])

        await ws2.send_json({"v": 1, "t": "conv.subscribe", "id": "sub2", "body": {"conv_id": "c1"}})
        timeout = 0.2
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ws2.receive_json(), timeout=timeout)

        await ws2.close()

    async def test_idempotency_persists_across_restart(self):
        client = await self._start_runtime()
        ws = await client.ws_connect("/v1/ws")
        await ws.send_json(
            {"v": 1, "t": "session.start", "id": "start1", "body": {"auth_token": "t", "device_id": "d1"}}
        )
        await ws.receive_json()

        await ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})
        send_frame = {
            "v": 1,
            "t": "conv.send",
            "id": "send1",
            "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW52", "ts": 1},
        }
        await ws.send_json(send_frame)
        await ws.receive_json()  # ack
        await ws.receive_json()  # event
        await ws.close()

        await self._servers[0][1].close()
        await self._servers[0][0].close()
        self._servers.clear()

        client2 = await self._start_runtime()
        ws_sub = await client2.ws_connect("/v1/ws")
        await ws_sub.send_json(
            {"v": 1, "t": "session.start", "id": "start2", "body": {"auth_token": "t", "device_id": "dsub"}}
        )
        await ws_sub.receive_json()
        await ws_sub.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})

        replay = await ws_sub.receive_json()
        self.assertEqual(replay["body"]["seq"], 1)

        ws_sender = await client2.ws_connect("/v1/ws")
        await ws_sender.send_json(
            {"v": 1, "t": "session.start", "id": "start3", "body": {"auth_token": "t", "device_id": "d1"}}
        )
        await ws_sender.receive_json()
        await ws_sender.send_json(send_frame)
        retry_ack = await ws_sender.receive_json()
        self.assertEqual(retry_ack["body"]["seq"], 1)

        timeout = 0.2
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ws_sub.receive_json(), timeout=timeout)

        await ws_sender.close()
        await ws_sub.close()


if __name__ == "__main__":
    unittest.main()
