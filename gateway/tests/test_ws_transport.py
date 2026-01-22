import asyncio
import base64
import hashlib
import importlib
import importlib.metadata
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

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
from ws_receive_util import assert_no_app_messages, recv_json_until
from gateway.ws_transport import RUNTIME_KEY, create_app
from mls_harness_util import HARNESS_DIR, ensure_harness_binary, make_harness_env, run_harness


def pack_dm_env(kind: int, payload_b64: str) -> str:
    env_bytes = bytes([kind]) + base64.b64decode(payload_b64, validate=True)
    return base64.b64encode(env_bytes).decode("utf-8")


def unpack_dm_env(env_b64: str) -> tuple[int, str]:
    env_bytes = base64.b64decode(env_b64, validate=True)
    kind = env_bytes[0]
    payload_b64 = base64.b64encode(env_bytes[1:]).decode("utf-8")
    return kind, payload_b64


def msg_id_for_env(env_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(env_b64, validate=True)).hexdigest()


class WsTransportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness_bin = ensure_harness_binary(timeout_s=120.0)
        cls.harness_env = make_harness_env()
        cls.harness_timeout = 8.0

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

    async def _run_harness(self, env: dict[str, str], *args: str) -> str:
        try:
            proc = await asyncio.wait_for(
                asyncio.to_thread(
                    run_harness,
                    args,
                    harness_bin=self.harness_bin,
                    cwd=HARNESS_DIR,
                    env=env,
                    timeout_s=self.harness_timeout,
                ),
                timeout=self.harness_timeout + 2.0,
            )
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            self.fail(f"mls-harness {' '.join(args)} timed out after {self.harness_timeout} seconds")

        if proc.returncode != 0:
            self.fail(
                f"mls-harness {' '.join(args)} failed with code {proc.returncode}\n"
                f"stdout:\n{proc.stdout.strip()}\n"
                f"stderr:\n{proc.stderr.strip()}\n"
            )
        return proc.stdout.strip()

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
        self.assertEqual(ack["body"]["conv_home"], "gw_local")
        self.assertEqual(ack["body"]["origin_gateway"], "gw_local")

        self.assertEqual(event["t"], "conv.event")
        self.assertEqual(event["body"]["seq"], 1)
        self.assertEqual(event["body"]["msg_id"], "m1")
        self.assertEqual(event["body"]["conv_home"], "gw_local")
        self.assertEqual(event["body"]["origin_gateway"], "gw_local")

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

        await assert_no_app_messages(ws, timeout=0.2)

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
        await assert_no_app_messages(ws2, timeout=0.2)

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
        runtime = self.app[RUNTIME_KEY]

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
        await assert_no_app_messages(member_ws, timeout=0.1)

        outsider_ws, _ = await self._start_session(auth_token="outsider", device_id="doutsider")
        await outsider_ws.send_json(
            {"v": 1, "t": "conv.send", "id": "send1", "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW4="}}
        )

        error = await outsider_ws.receive_json()
        self.assertEqual(error["t"], "error")
        self.assertEqual(error["body"]["code"], "forbidden")

        await assert_no_app_messages(member_ws, timeout=0.2)

        await owner_ws.close()
        await member_ws.close()
        await outsider_ws.close()

    async def test_subscription_revoked_on_removal(self):
        owner_ws, owner_ready = await self._start_session(auth_token="owner", device_id="downer")
        await self._create_room(owner_ready["body"]["session_token"], "c1", members=["member"])

        member_ws, _ = await self._start_session(auth_token="member", device_id="dmember")
        await member_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub", "body": {"conv_id": "c1"}})

        resp = await self.client.post(
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

        await assert_no_app_messages(member_ws, timeout=0.2)

        await owner_ws.close()
        await member_ws.close()

    async def test_owner_can_promote_and_demote_admin(self):
        owner_ws, owner_ready = await self._start_session(auth_token="owner", device_id="downer")
        await self._create_room(owner_ready["body"]["session_token"], "c1", members=["member"])

        resp = await self.client.post(
            "/v1/rooms/promote",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

        admin_ws, admin_ready = await self._start_session(auth_token="member", device_id="dmember")
        invite_resp = await self.client.post(
            "/v1/rooms/invite",
            json={"conv_id": "c1", "members": ["new"]},
            headers={"Authorization": f"Bearer {admin_ready['body']['session_token']}"},
        )
        self.assertEqual(invite_resp.status, 200)
        await invite_resp.json()

        remove_resp = await self.client.post(
            "/v1/rooms/remove",
            json={"conv_id": "c1", "members": ["new"]},
            headers={"Authorization": f"Bearer {admin_ready['body']['session_token']}"},
        )
        self.assertEqual(remove_resp.status, 200)
        await remove_resp.json()

        demote_resp = await self.client.post(
            "/v1/rooms/demote",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(demote_resp.status, 200)
        await demote_resp.json()

        forbidden_resp = await self.client.post(
            "/v1/rooms/invite",
            json={"conv_id": "c1", "members": ["late"]},
            headers={"Authorization": f"Bearer {admin_ready['body']['session_token']}"},
        )
        self.assertEqual(forbidden_resp.status, 403)
        await forbidden_resp.json()

        await admin_ws.close()
        await owner_ws.close()

    async def test_room_offline_join_leave_churn_replay_enforced(self):
        owner_ws, owner_ready = await self._start_session(auth_token="owner", device_id="downer")
        await self._create_room(owner_ready["body"]["session_token"], "c1", members=["member"])

        member_ws, _ = await self._start_session(auth_token="member", device_id="dmember")
        await member_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub1", "body": {"conv_id": "c1", "from_seq": 1}})
        await member_ws.close()

        await owner_ws.send_json(
            {"v": 1, "t": "conv.send", "id": "send1", "body": {"conv_id": "c1", "msg_id": "m1", "env": "ZW4=", "ts": 1}}
        )
        ack1 = await owner_ws.receive_json()
        self.assertEqual(ack1["t"], "conv.acked")
        self.assertEqual(ack1["body"]["seq"], 1)

        await owner_ws.send_json(
            {"v": 1, "t": "conv.send", "id": "send2", "body": {"conv_id": "c1", "msg_id": "m2", "env": "ZW4=", "ts": 2}}
        )
        ack2 = await owner_ws.receive_json()
        self.assertEqual(ack2["t"], "conv.acked")
        self.assertEqual(ack2["body"]["seq"], 2)

        member_ws_replay, _ = await self._start_session(auth_token="member", device_id="dmember")
        await member_ws_replay.send_json(
            {"v": 1, "t": "conv.subscribe", "id": "replay1", "body": {"conv_id": "c1", "from_seq": 1}}
        )

        loop = asyncio.get_running_loop()
        event1 = await recv_json_until(
            member_ws_replay, deadline=loop.time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.event"
        )
        event2 = await recv_json_until(
            member_ws_replay, deadline=loop.time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.event"
        )

        self.assertEqual(event1["body"]["seq"], 1)
        self.assertEqual(event1["body"]["msg_id"], "m1")
        self.assertEqual(event2["body"]["seq"], 2)
        self.assertEqual(event2["body"]["msg_id"], "m2")

        await member_ws_replay.send_json({"v": 1, "t": "conv.ack", "body": {"conv_id": "c1", "seq": 2}})
        await member_ws_replay.close()

        remove_resp = await self.client.post(
            "/v1/rooms/remove",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(remove_resp.status, 200)
        await remove_resp.json()

        await owner_ws.send_json(
            {"v": 1, "t": "conv.send", "id": "send3", "body": {"conv_id": "c1", "msg_id": "m3", "env": "ZW4=", "ts": 3}}
        )
        ack3 = await owner_ws.receive_json()
        self.assertEqual(ack3["t"], "conv.acked")
        self.assertEqual(ack3["body"]["seq"], 3)

        member_ws_forbidden, _ = await self._start_session(auth_token="member", device_id="dmember")
        await member_ws_forbidden.send_json(
            {"v": 1, "t": "conv.subscribe", "id": "replay2", "body": {"conv_id": "c1", "from_seq": 3}}
        )

        error = await recv_json_until(member_ws_forbidden, deadline=loop.time() + 1.0, predicate=lambda payload: True)
        self.assertEqual(error["t"], "error")
        self.assertEqual(error["body"]["code"], "forbidden")
        self.assertIn(error["body"].get("message"), ("membership revoked", "not a member"))
        await assert_no_app_messages(member_ws_forbidden, timeout=0.2)
        await member_ws_forbidden.close()

        invite_resp = await self.client.post(
            "/v1/rooms/invite",
            json={"conv_id": "c1", "members": ["member"]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(invite_resp.status, 200)
        await invite_resp.json()

        await owner_ws.send_json(
            {"v": 1, "t": "conv.send", "id": "send4", "body": {"conv_id": "c1", "msg_id": "m4", "env": "ZW4=", "ts": 4}}
        )
        ack4 = await owner_ws.receive_json()
        self.assertEqual(ack4["t"], "conv.acked")
        self.assertEqual(ack4["body"]["seq"], 4)

        member_ws_final, _ = await self._start_session(auth_token="member", device_id="dmember")
        await member_ws_final.send_json(
            {"v": 1, "t": "conv.subscribe", "id": "replay3", "body": {"conv_id": "c1", "from_seq": 4}}
        )

        final_event = await recv_json_until(
            member_ws_final, deadline=loop.time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.event"
        )

        self.assertEqual(final_event["body"]["seq"], 4)
        self.assertEqual(final_event["body"]["msg_id"], "m4")

        await assert_no_app_messages(member_ws_final, timeout=0.2)

        await member_ws_final.close()
        await owner_ws.close()

    async def test_room_bootstrap_add_and_app_roundtrip_over_ws(self):
        env: dict[str, str] = dict(self.harness_env)
        conv_id = "ws-room-1"

        owner_ws, owner_ready = await self._start_session(auth_token="owner", device_id="dev-owner")
        peer_one_ws, peer_one_ready = await self._start_session(auth_token="peer-one", device_id="dev-peer-1")
        peer_two_ws, peer_two_ready = await self._start_session(auth_token="peer-two", device_id="dev-peer-2")

        await self._create_room(owner_ready["body"]["session_token"], conv_id)
        invite_resp = await self.client.post(
            "/v1/rooms/invite",
            json={"conv_id": conv_id, "members": [peer_one_ready["body"]["user_id"], peer_two_ready["body"]["user_id"]]},
            headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
        )
        self.assertEqual(invite_resp.status, 200)
        await invite_resp.json()

        for ws, req_id in ((owner_ws, "sub-owner"), (peer_one_ws, "sub-one"), (peer_two_ws, "sub-two")):
            await ws.send_json({"v": 1, "t": "conv.subscribe", "id": req_id, "body": {"conv_id": conv_id, "from_seq": 1}})

        async def publish_keypackages(session_token: str, device_id: str, keypackages: list[str]):
            resp = await self.client.post(
                "/v1/keypackages",
                json={"device_id": device_id, "keypackages": keypackages},
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(resp.status, 200)
            await resp.json()

        async def fetch_keypackages(session_token: str, user_id: str, count: int = 1) -> list[str]:
            resp = await self.client.post(
                "/v1/keypackages/fetch",
                json={"user_id": user_id, "count": count},
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(resp.status, 200)
            body = await resp.json()
            return body["keypackages"]

        async def read_event(ws, expected_seq: int) -> dict:
            loop = asyncio.get_running_loop()
            event = await recv_json_until(
                ws,
                deadline=loop.time() + 1.0,
                predicate=lambda payload: payload.get("t") == "conv.event" and payload["body"]["seq"] == expected_seq,
            )
            return event

        expected_seq = 1
        with (
            tempfile.TemporaryDirectory(prefix="owner-") as owner_dir,
            tempfile.TemporaryDirectory(prefix="peer-one-") as peer_one_dir,
            tempfile.TemporaryDirectory(prefix="peer-two-") as peer_two_dir,
            tempfile.TemporaryDirectory(prefix="peer-three-") as peer_three_dir,
            tempfile.TemporaryDirectory(prefix="owner-shadow-1-") as owner_shadow_one_dir,
            tempfile.TemporaryDirectory(prefix="owner-shadow-2-") as owner_shadow_two_dir,
        ):
            owner_dir = Path(owner_dir)
            peer_one_dir = Path(peer_one_dir)
            peer_two_dir = Path(peer_two_dir)
            peer_three_dir = Path(peer_three_dir)
            owner_shadow_one_dir = Path(owner_shadow_one_dir)
            owner_shadow_two_dir = Path(owner_shadow_two_dir)

            owner_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", str(owner_dir), "--name", "owner", "--seed", "9201"
            )
            peer_one_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", str(peer_one_dir), "--name", "peer_one", "--seed", "9202"
            )
            peer_two_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", str(peer_two_dir), "--name", "peer_two", "--seed", "9203"
            )

            await publish_keypackages(owner_ready["body"]["session_token"], "dev-owner", [owner_kp])
            await publish_keypackages(peer_one_ready["body"]["session_token"], "dev-peer-1", [peer_one_kp])
            await publish_keypackages(peer_two_ready["body"]["session_token"], "dev-peer-2", [peer_two_kp])

            peer_one_fetch = await fetch_keypackages(owner_ready["body"]["session_token"], peer_one_ready["body"]["user_id"])
            peer_two_fetch = await fetch_keypackages(owner_ready["body"]["session_token"], peer_two_ready["body"]["user_id"])
            self.assertEqual(len(peer_one_fetch), 1)
            self.assertEqual(len(peer_two_fetch), 1)

            init_output = await self._run_harness(
                env,
                "group-init",
                "--state-dir",
                str(owner_dir),
                "--peer-keypackage",
                peer_one_fetch[0],
                "--peer-keypackage",
                peer_two_fetch[0],
                "--group-id",
                "d3Mtcm9vbQ==",
                "--seed",
                "8301",
            )
            init_payload = json.loads(init_output)

            welcome_env = pack_dm_env(1, init_payload["welcome"])
            await owner_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "welcome-1",
                    "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(welcome_env), "env": welcome_env},
                }
            )
            welcome_ack = await recv_json_until(
                owner_ws, deadline=asyncio.get_running_loop().time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.acked"
            )
            self.assertEqual(welcome_ack["id"], "welcome-1")
            self.assertEqual(welcome_ack["body"]["seq"], expected_seq)

            welcome_events = {
                "owner": await read_event(owner_ws, expected_seq),
                "peer_one": await read_event(peer_one_ws, expected_seq),
                "peer_two": await read_event(peer_two_ws, expected_seq),
            }
            for event in welcome_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            _, peer_one_welcome = unpack_dm_env(welcome_events["peer_one"]["body"]["env"])
            _, peer_two_welcome = unpack_dm_env(welcome_events["peer_two"]["body"]["env"])
            await self._run_harness(env, "dm-join", "--state-dir", str(peer_one_dir), "--welcome", peer_one_welcome)
            await self._run_harness(env, "dm-join", "--state-dir", str(peer_two_dir), "--welcome", peer_two_welcome)

            expected_seq += 1
            commit_env = pack_dm_env(2, init_payload["commit"])
            await owner_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "commit-1",
                    "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(commit_env), "env": commit_env},
                }
            )
            commit_ack = await recv_json_until(
                owner_ws, deadline=asyncio.get_running_loop().time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.acked"
            )
            self.assertEqual(commit_ack["id"], "commit-1")
            self.assertEqual(commit_ack["body"]["seq"], expected_seq)

            commit_events = {
                "owner": await read_event(owner_ws, expected_seq),
                "peer_one": await read_event(peer_one_ws, expected_seq),
                "peer_two": await read_event(peer_two_ws, expected_seq),
            }
            for event in commit_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("owner", owner_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                _, commit_payload = unpack_dm_env(commit_events[member]["body"]["env"])
                await self._run_harness(env, "dm-commit-apply", "--state-dir", str(state_dir), "--commit", commit_payload)

            expected_seq += 1
            first_plaintext = "ws-room-app-1"
            shutil.copyfile(owner_dir / "participant.gob", owner_shadow_one_dir / "participant.gob")
            first_cipher = await self._run_harness(
                env, "dm-encrypt", "--state-dir", str(owner_dir), "--plaintext", first_plaintext
            )
            first_env = pack_dm_env(3, first_cipher)
            await owner_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "app-1",
                    "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(first_env), "env": first_env},
                }
            )
            app_ack = await recv_json_until(
                owner_ws, deadline=asyncio.get_running_loop().time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.acked"
            )
            self.assertEqual(app_ack["id"], "app-1")
            self.assertEqual(app_ack["body"]["seq"], expected_seq)

            app_events = {
                "owner": await read_event(owner_ws, expected_seq),
                "peer_one": await read_event(peer_one_ws, expected_seq),
                "peer_two": await read_event(peer_two_ws, expected_seq),
            }
            for event in app_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("owner", owner_shadow_one_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                _, app_payload = unpack_dm_env(app_events[member]["body"]["env"])
                decrypted = await self._run_harness(
                    env, "dm-decrypt", "--state-dir", str(state_dir), "--ciphertext", app_payload
                )
                self.assertEqual(decrypted, first_plaintext)

            peer_three_ws, peer_three_ready = await self._start_session(auth_token="peer-three", device_id="dev-peer-3")
            invite_three = await self.client.post(
                "/v1/rooms/invite",
                json={"conv_id": conv_id, "members": [peer_three_ready["body"]["user_id"]]},
                headers={"Authorization": f"Bearer {owner_ready['body']['session_token']}"},
            )
            self.assertEqual(invite_three.status, 200)
            await invite_three.json()

            await peer_three_ws.send_json(
                {"v": 1, "t": "conv.subscribe", "id": "sub-three", "body": {"conv_id": conv_id, "from_seq": 1}}
            )

            peer_three_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", str(peer_three_dir), "--name", "peer_three", "--seed", "9204"
            )
            await publish_keypackages(peer_three_ready["body"]["session_token"], "dev-peer-3", [peer_three_kp])
            peer_three_fetch = await fetch_keypackages(
                owner_ready["body"]["session_token"], peer_three_ready["body"]["user_id"]
            )
            self.assertEqual(len(peer_three_fetch), 1)

            add_output = await self._run_harness(
                env, "group-add", "--state-dir", str(owner_dir), "--peer-keypackage", peer_three_fetch[0], "--seed", "8302"
            )
            add_payload = json.loads(add_output)

            expected_seq += 1
            add_proposals = add_payload["proposals"]
            self.assertEqual(len(add_proposals), 1)
            add_proposal_env = pack_dm_env(2, add_proposals[0])
            await owner_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "proposal-2",
                    "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(add_proposal_env), "env": add_proposal_env},
                }
            )
            add_proposal_ack = await recv_json_until(
                owner_ws, deadline=asyncio.get_running_loop().time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.acked"
            )
            self.assertEqual(add_proposal_ack["id"], "proposal-2")
            self.assertEqual(add_proposal_ack["body"]["seq"], expected_seq)

            add_proposal_events = {
                "owner": await read_event(owner_ws, expected_seq),
                "peer_one": await read_event(peer_one_ws, expected_seq),
                "peer_two": await read_event(peer_two_ws, expected_seq),
                "peer_three": await read_event(peer_three_ws, expected_seq),
            }
            for event in add_proposal_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                _, proposal_payload = unpack_dm_env(add_proposal_events[member]["body"]["env"])
                await self._run_harness(
                    env, "dm-commit-apply", "--state-dir", str(state_dir), "--commit", proposal_payload
                )

            expected_seq += 1
            add_welcome_env = pack_dm_env(1, add_payload["welcome"])
            await owner_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "welcome-2",
                    "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(add_welcome_env), "env": add_welcome_env},
                }
            )
            add_welcome_ack = await recv_json_until(
                owner_ws, deadline=asyncio.get_running_loop().time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.acked"
            )
            self.assertEqual(add_welcome_ack["id"], "welcome-2")
            self.assertEqual(add_welcome_ack["body"]["seq"], expected_seq)

            add_welcome_events = {
                "owner": await read_event(owner_ws, expected_seq),
                "peer_one": await read_event(peer_one_ws, expected_seq),
                "peer_two": await read_event(peer_two_ws, expected_seq),
                "peer_three": await read_event(peer_three_ws, expected_seq),
            }
            for event in add_welcome_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            _, peer_three_welcome = unpack_dm_env(add_welcome_events["peer_three"]["body"]["env"])
            await self._run_harness(
                env, "dm-join", "--state-dir", str(peer_three_dir), "--welcome", peer_three_welcome
            )

            expected_seq += 1
            add_commit_env = pack_dm_env(2, add_payload["commit"])
            await owner_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "commit-2",
                    "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(add_commit_env), "env": add_commit_env},
                }
            )
            add_commit_ack = await recv_json_until(
                owner_ws, deadline=asyncio.get_running_loop().time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.acked"
            )
            self.assertEqual(add_commit_ack["id"], "commit-2")
            self.assertEqual(add_commit_ack["body"]["seq"], expected_seq)

            add_commit_events = {
                "owner": await read_event(owner_ws, expected_seq),
                "peer_one": await read_event(peer_one_ws, expected_seq),
                "peer_two": await read_event(peer_two_ws, expected_seq),
                "peer_three": await read_event(peer_three_ws, expected_seq),
            }
            for event in add_commit_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("owner", owner_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
                ("peer_three", peer_three_dir),
            ):
                _, commit_payload = unpack_dm_env(add_commit_events[member]["body"]["env"])
                await self._run_harness(env, "dm-commit-apply", "--state-dir", str(state_dir), "--commit", commit_payload)

            expected_seq += 1
            second_plaintext = "ws-room-app-2"
            shutil.copyfile(owner_dir / "participant.gob", owner_shadow_two_dir / "participant.gob")
            second_cipher = await self._run_harness(
                env, "dm-encrypt", "--state-dir", str(owner_dir), "--plaintext", second_plaintext
            )
            second_env = pack_dm_env(3, second_cipher)
            await owner_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "app-2",
                    "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(second_env), "env": second_env},
                }
            )
            second_ack = await recv_json_until(
                owner_ws, deadline=asyncio.get_running_loop().time() + 1.0, predicate=lambda payload: payload.get("t") == "conv.acked"
            )
            self.assertEqual(second_ack["id"], "app-2")
            self.assertEqual(second_ack["body"]["seq"], expected_seq)

            second_events = {
                "owner": await read_event(owner_ws, expected_seq),
                "peer_one": await read_event(peer_one_ws, expected_seq),
                "peer_two": await read_event(peer_two_ws, expected_seq),
                "peer_three": await read_event(peer_three_ws, expected_seq),
            }
            for event in second_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("owner", owner_shadow_two_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
                ("peer_three", peer_three_dir),
            ):
                _, app_payload = unpack_dm_env(second_events[member]["body"]["env"])
                decrypted = await self._run_harness(
                    env, "dm-decrypt", "--state-dir", str(state_dir), "--ciphertext", app_payload
                )
                self.assertEqual(decrypted, second_plaintext)

            await peer_three_ws.close()

        await owner_ws.close()
        await peer_one_ws.close()
        await peer_two_ws.close()


if __name__ == "__main__":
    unittest.main()
