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

    async def _start_session(self, client: TestClient, *, auth_token: str = "t", device_id: str = "d1"):
        ws = await client.ws_connect("/v1/ws")
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

    async def _create_room(self, client: TestClient, session_token: str, conv_id: str, members: list[str] | None = None):
        resp = await client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": members or []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def test_resume_persists_cursors_and_sessions(self):
        client = await self._start_runtime()
        ws, ready = await self._start_session(client)
        self.assertEqual("session.ready", ready["t"])
        self.assertIn("resume_token", ready["body"])
        resume_token = ready["body"]["resume_token"]
        await self._create_room(client, ready["body"]["session_token"], "c1")

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
        ws, ready = await self._start_session(client)
        await self._create_room(client, ready["body"]["session_token"], "c1")

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
        ws_sub, _ = await self._start_session(client2, device_id="dsub")
        await ws_sub.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1", "from_seq": 1}})

        replay = await ws_sub.receive_json()
        self.assertEqual(replay["body"]["seq"], 1)

        ws_sender, _ = await self._start_session(client2)
        await ws_sender.send_json(send_frame)
        retry_ack = await ws_sender.receive_json()
        self.assertEqual(retry_ack["body"]["seq"], 1)

        timeout = 0.2
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ws_sub.receive_json(), timeout=timeout)

        await ws_sender.close()
        await ws_sub.close()

    async def test_non_member_cannot_subscribe(self):
        client = await self._start_runtime()
        owner_ws, ready = await self._start_session(client, auth_token="owner")
        await self._create_room(client, ready["body"]["session_token"], "c1")

        outsider_ws, _ = await self._start_session(client, auth_token="outsider", device_id="dother")
        await outsider_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1"}})
        error = await outsider_ws.receive_json()
        self.assertEqual(error["body"]["code"], "forbidden")

        await owner_ws.close()
        await outsider_ws.close()

    async def test_subscription_revoked_on_removal(self):
        client = await self._start_runtime()
        owner_ws, owner_ready = await self._start_session(client, auth_token="owner", device_id="downer")
        await self._create_room(client, owner_ready["body"]["session_token"], "c1", members=["member"])

        member_ws, _ = await self._start_session(client, auth_token="member", device_id="dmember")
        await member_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1"}})

        resp = await client.post(
            "/v1/rooms/remove",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

        await owner_ws.send_json(
            {
                "v": 1,
                "t": "conv.send",
                "id": "send1",
                "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW4=", "ts": 1},
            }
        )
        await owner_ws.receive_json()  # ack

        error = await member_ws.receive_json()
        self.assertEqual(error["t"], "error")
        self.assertEqual(error["body"], {"code": "forbidden", "message": "membership revoked"})

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(member_ws.receive_json(), timeout=0.2)

        await owner_ws.close()
        await member_ws.close()

    async def test_owner_can_promote_and_demote_admin(self):
        client = await self._start_runtime()
        owner_ws, owner_ready = await self._start_session(client, auth_token="owner", device_id="downer")
        await self._create_room(client, owner_ready["body"]["session_token"], "c1", members=["member"])

        resp = await client.post(
            "/v1/rooms/promote",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

        admin_ws, admin_ready = await self._start_session(client, auth_token="member", device_id="dmember")
        invite_resp = await client.post(
            "/v1/rooms/invite",
            json={"conv_id": "c1", "members": ["new"]},
            headers={"Authorization": f"Bearer {admin_ready['body']['session_token']}"},
        )
        self.assertEqual(invite_resp.status, 200)
        await invite_resp.json()

        remove_resp = await client.post(
            "/v1/rooms/remove",
            json={"conv_id": "c1", "members": ["new"]},
            headers={"Authorization": f"Bearer {admin_ready['body']['session_token']}"},
        )
        self.assertEqual(remove_resp.status, 200)
        await remove_resp.json()

        demote_resp = await client.post(
            "/v1/rooms/demote",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(demote_resp.status, 200)
        await demote_resp.json()

        forbidden_resp = await client.post(
            "/v1/rooms/invite",
            json={"conv_id": "c1", "members": ["late"]},
            headers={"Authorization": f"Bearer {admin_ready['body']['session_token']}"},
        )
        self.assertEqual(forbidden_resp.status, 403)
        await forbidden_resp.json()

        await admin_ws.close()
        await owner_ws.close()


if __name__ == "__main__":
    unittest.main()
