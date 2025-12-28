import asyncio
import importlib
import unittest

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is not None:
    from aiohttp.test_utils import TestClient, TestServer
else:  # pragma: no cover - offline fallback
    from gateway.aiohttp_stub.test_utils import TestClient, TestServer

from gateway.ws_transport import create_app


class WsTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(ping_interval_s=3600)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def _connect(self):
        return await self.client.ws_connect("/v1/ws")

    async def _start_session(self):
        ws = await self._connect()
        await ws.send_json(
            {"v": 1, "t": "session.start", "id": "start1", "body": {"auth_token": "t", "device_id": "d1"}}
        )
        ready = await ws.receive_json()
        return ws, ready

    async def test_session_start_returns_ready(self):
        ws, ready = await self._start_session()
        await ws.close()

        self.assertEqual(ready["t"], "session.ready")
        body = ready["body"]
        self.assertTrue(body["session_token"])
        self.assertTrue(body["resume_token"])
        self.assertEqual(body["cursors"], [])

    async def test_subscribe_and_send_echo(self):
        ws, _ = await self._start_session()

        await ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})
        await ws.send_json(
            {
                "v": 1,
                "t": "conv.send",
                "id": "send1",
                "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW52", "ts": 1},
            }
        )

        ack = await ws.receive_json()
        event = await ws.receive_json()

        self.assertEqual(ack["t"], "conv.acked")
        self.assertEqual(ack["id"], "send1")
        self.assertEqual(ack["body"]["seq"], 1)

        self.assertEqual(event["t"], "conv.event")
        self.assertEqual(event["body"]["seq"], 1)
        self.assertEqual(event["body"]["msg_id"], "m1")

        await ws.close()

    async def test_idempotent_retry_does_not_duplicate_event(self):
        ws, _ = await self._start_session()

        await ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})
        send_frame = {
            "v": 1,
            "t": "conv.send",
            "id": "send1",
            "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW52", "ts": 1},
        }
        await ws.send_json(send_frame)
        ack = await ws.receive_json()
        event = await ws.receive_json()

        self.assertEqual(event["body"]["seq"], 1)
        self.assertEqual(ack["body"]["seq"], 1)

        await ws.send_json(send_frame)
        retry_ack = await ws.receive_json()
        self.assertEqual(retry_ack["body"]["seq"], 1)

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.receive_json(), timeout=0.2)

        await ws.close()

    async def test_ack_and_resume_cursor(self):
        ws, ready = await self._start_session()
        resume_token = ready["body"]["resume_token"]

        await ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})
        await ws.send_json(
            {
                "v": 1,
                "t": "conv.send",
                "id": "send1",
                "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW52", "ts": 1},
            }
        )
        await ws.receive_json()  # ack
        await ws.receive_json()  # event

        await ws.send_json({"v": 1, "t": "conv.ack", "body": {"conv_id": "c1", "seq": 1}})
        await ws.close()

        ws2 = await self._connect()
        await ws2.send_json({"v": 1, "t": "session.resume", "id": "resume1", "body": {"resume_token": resume_token}})
        ready2 = await ws2.receive_json()
        body = ready2["body"]

        self.assertIn({"conv_id": "c1", "next_seq": 2}, body["cursors"])

        await ws2.send_json({"v": 1, "t": "conv.subscribe", "id": "sub2", "body": {"conv_id": "c1"}})
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ws2.receive_json(), timeout=0.2)

        await ws2.close()


if __name__ == "__main__":
    unittest.main()
