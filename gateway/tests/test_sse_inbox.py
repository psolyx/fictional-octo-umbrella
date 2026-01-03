import asyncio
import importlib
import importlib.metadata
import json
import unittest

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway SSE tests")

from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway SSE tests, found {_installed_aiohttp}"
    )

from gateway.ws_transport import create_app


async def read_sse_event(response, timeout: float = 1.0):
    event_type = None
    data = None
    while True:
        line = await asyncio.wait_for(response.content.readline(), timeout=timeout)
        if not line:
            raise AssertionError("SSE stream closed unexpectedly")
        text = line.decode().rstrip("\n")
        if text == "":
            if data is not None:
                return event_type, data
            continue
        if text.startswith(":"):
            continue
        if text.startswith("event:"):
            event_type = text[len("event:") :].strip()
        elif text.startswith("data:"):
            data = json.loads(text[len("data:") :].strip())


class SseInboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(ping_interval_s=3600)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def _start_session_http(self, *, auth_token: str = "t", device_id: str = "d1"):
        resp = await self.client.post(
            "/v1/session/start",
            json={"auth_token": auth_token, "device_id": device_id},
        )
        self.assertEqual(resp.status, 200)
        return await resp.json()

    async def _create_room(self, session_token: str, conv_id: str, members: list[str] | None = None):
        resp = await self.client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": members or []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _post_inbox(self, session_token: str, frame: dict):
        resp = await self.client.post(
            "/v1/inbox", json=frame, headers={"Authorization": f"Bearer {session_token}"}
        )
        return resp

    async def test_inbox_send_delivered_over_sse(self):
        ready = await self._start_session_http()
        session_token = ready["session_token"]
        await self._create_room(session_token, "c1")

        sse_resp = await self.client.get(
            "/v1/sse",
            params={"conv_id": "c1", "from_seq": "1"},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(sse_resp.status, 200)

        send_frame = {
            "v": 1,
            "t": "conv.send",
            "id": "send1",
            "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW52"},
        }
        resp1 = await self._post_inbox(session_token, send_frame)
        self.assertEqual(resp1.status, 200)
        body1 = await resp1.json()

        resp2 = await self._post_inbox(session_token, send_frame)
        self.assertEqual(resp2.status, 200)
        body2 = await resp2.json()

        self.assertEqual(body1["seq"], body2["seq"])

        event_type, payload = await read_sse_event(sse_resp)
        self.assertEqual(event_type, "conv.event")
        self.assertEqual(payload["body"]["msg_id"], "m1")

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(read_sse_event(sse_resp), timeout=0.2)

        await sse_resp.release()

    async def test_sse_resume_uses_cursor_when_from_seq_omitted(self):
        ready = await self._start_session_http()
        session_token = ready["session_token"]
        await self._create_room(session_token, "c1")

        sse_resp = await self.client.get(
            "/v1/sse",
            params={"conv_id": "c1", "from_seq": "1"},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(sse_resp.status, 200)

        for idx in range(2):
            frame = {
                "v": 1,
                "t": "conv.send",
                "body": {"conv_id": "c1", "msg_id": f"m{idx}", "env": "ZW4="},
            }
            resp = await self._post_inbox(session_token, frame)
            self.assertEqual(resp.status, 200)
            await resp.json()

        first_event = await read_sse_event(sse_resp)
        second_event = await read_sse_event(sse_resp)

        self.assertEqual(first_event[1]["body"]["seq"], 1)
        self.assertEqual(second_event[1]["body"]["seq"], 2)

        ack_resp = await self._post_inbox(
            session_token, {"v": 1, "t": "conv.ack", "body": {"conv_id": "c1", "seq": 2}}
        )
        self.assertEqual(ack_resp.status, 200)
        await ack_resp.json()

        await sse_resp.release()

        resumed_resp = await self.client.get(
            "/v1/sse",
            params={"conv_id": "c1"},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resumed_resp.status, 200)

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(read_sse_event(resumed_resp), timeout=0.2)

        send3 = {
            "v": 1,
            "t": "conv.send",
            "body": {"conv_id": "c1", "msg_id": "m3", "env": "ZW4="},
        }
        resp3 = await self._post_inbox(session_token, send3)
        self.assertEqual(resp3.status, 200)
        await resp3.json()

        _, payload3 = await read_sse_event(resumed_resp)
        self.assertEqual(payload3["body"]["seq"], 3)

        await resumed_resp.release()
