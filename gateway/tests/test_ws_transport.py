import asyncio
import importlib
import importlib.metadata
import unittest

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway WS tests")

from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway WS tests, found {_installed_aiohttp}"
    )

from gateway import ws_transport as wst
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

    async def _start_session(self, *, auth_token: str = "t", device_id: str = "d1"):
        ws = await self._connect()
        await ws.send_json(
            {
                "v": 1,
                "t": "session.start",
                "id": "start1",
                "body": {"auth_token": auth_token, "device_id": device_id},
            }
        )
        ready = await ws.receive_json()
        return ws, ready

    async def _create_room(self, session_token: str, conv_id: str, members: list[str] | None = None):
        resp = await self.client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": members or []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def test_session_start_returns_ready(self):
        ws, ready = await self._start_session()
        await ws.close()

        self.assertEqual(ready["t"], "session.ready")
        body = ready["body"]
        self.assertTrue(body["session_token"])
        self.assertTrue(body["resume_token"])
        self.assertEqual(body["cursors"], [])

    async def test_subscribe_and_send_echo(self):
        ws, ready = await self._start_session()
        await self._create_room(ready["body"]["session_token"], "c1")

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
        ws, ready = await self._start_session()
        await self._create_room(ready["body"]["session_token"], "c1")

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
        await self._create_room(ready["body"]["session_token"], "c1")

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

    async def test_broadcasts_preserve_seq_order_with_concurrent_sends(self):
        original_send_json = wst.web.WebSocketResponse.send_json

        async def delayed_send_json(self, data, *args, **kwargs):
            if data.get("t") == "conv.acked" and data.get("body", {}).get("msg_id") == "m1":
                await asyncio.sleep(0.05)
            return await original_send_json(self, data, *args, **kwargs)

        wst.web.WebSocketResponse.send_json = delayed_send_json

        sub_ws, sub_ready = await self._start_session(device_id="dsub")
        await self._create_room(sub_ready["body"]["session_token"], "c1")
        await sub_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})

        ws1, _ = await self._start_session(device_id="d1")
        ws2, _ = await self._start_session(device_id="d2")

        try:
            await asyncio.gather(
                ws1.send_json(
                    {"v": 1, "t": "conv.send", "id": "send1", "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW4=", "ts": 1}}
                ),
                ws2.send_json(
                    {"v": 1, "t": "conv.send", "id": "send2", "body": {"conv_id": "c1", "msg_id": "m2", "env": "ZW4=", "ts": 2}}
                ),
            )

            ack1 = await ws1.receive_json()
            ack2 = await ws2.receive_json()

            self.assertEqual(ack1["t"], "conv.acked")
            self.assertEqual(ack2["t"], "conv.acked")

            seqs = []
            while len(seqs) < 2:
                msg = await sub_ws.receive_json()
                if msg["t"] == "conv.event":
                    seqs.append(msg["body"]["seq"])

            self.assertEqual(seqs, [1, 2])
        finally:
            wst.web.WebSocketResponse.send_json = original_send_json
            await ws1.close()
            await ws2.close()
            await sub_ws.close()

    async def test_replay_events_flush_before_live_events(self):
        runtime = self.app["runtime"]

        ws_sender, ready = await self._start_session()
        await self._create_room(ready["body"]["session_token"], "c1")
        await ws_sender.send_json(
            {"v": 1, "t": "conv.send", "id": "send1", "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW4=", "ts": 1}}
        )
        await ws_sender.receive_json()  # ack

        original_subscribe = runtime.hub.subscribe

        def wrapped_subscribe(device_id: str, conv_id: str, callback):
            subscription = original_subscribe(device_id, conv_id, callback)
            seq, event, created = runtime.log.append(conv_id, "m2", "ZW52Mg==", "d1", wst._now_ms())
            if created:
                runtime.hub.broadcast(event)
            return subscription

        runtime.hub.subscribe = wrapped_subscribe

        ws_sub, _ = await self._start_session(device_id="dsub")

        try:
            await ws_sub.send_json({"v": 1, "t": "conv.subscribe", "id": "sub2", "body": {"conv_id": "c1", "from_seq": 1}})

            events = []
            while len(events) < 2:
                msg = await ws_sub.receive_json()
                if msg["t"] == "conv.event":
                    events.append(msg)

            self.assertEqual(events[0]["body"]["seq"], 1)
            self.assertEqual(events[1]["body"]["seq"], 2)
        finally:
            runtime.hub.subscribe = original_subscribe
            await ws_sender.close()
            await ws_sub.close()

    async def test_forbidden_for_non_member_subscribe(self):
        owner_ws, ready = await self._start_session(auth_token="owner", device_id="downer")
        await self._create_room(ready["body"]["session_token"], "c1")

        other_ws, _ = await self._start_session(auth_token="other", device_id="dother")
        await other_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1"}})
        error = await other_ws.receive_json()
        self.assertEqual(error["t"], "error")
        self.assertEqual(error["body"]["code"], "forbidden")

        await owner_ws.close()
        await other_ws.close()

    async def test_forbidden_for_non_member_send(self):
        owner_ws, ready = await self._start_session(auth_token="owner", device_id="downer")
        await self._create_room(ready["body"]["session_token"], "c1")

        member_ws, _ = await self._start_session(auth_token="member", device_id="dmember")
        resp = await self.client.post(
            "/v1/rooms/invite",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {ready['body']['session_token']}"},
        )
        self.assertEqual(resp.status, 200)
        await member_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1"}})
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(member_ws.receive_json(), timeout=0.1)

        outsider_ws, _ = await self._start_session(auth_token="outsider", device_id="doutsider")
        await outsider_ws.send_json(
            {"v": 1, "t": "conv.send", "id": "send1", "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW4="}}
        )

        error = await outsider_ws.receive_json()
        self.assertEqual(error["t"], "error")
        self.assertEqual(error["body"]["code"], "forbidden")

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(member_ws.receive_json(), timeout=0.2)

        await owner_ws.close()
        await member_ws.close()
        await outsider_ws.close()


if __name__ == "__main__":
    unittest.main()
