import asyncio
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY_SRC = ROOT_DIR / "gateway" / "src"
GATEWAY_TESTS = ROOT_DIR / "gateway" / "tests"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))
if str(GATEWAY_TESTS) not in sys.path:
    sys.path.insert(0, str(GATEWAY_TESTS))

from cli_app import dm_envelope
from gateway.ws_transport import create_app
from mls_harness_util import HARNESS_DIR, ensure_harness_binary, make_harness_env, run_harness


def _msg_id_for_env(env_b64: str) -> str:
    env_bytes = base64.b64decode(env_b64, validate=True)
    return hashlib.sha256(env_bytes).hexdigest()


async def _ws_receive_payload(ws, *, deadline: float) -> dict:
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError("Timed out waiting for websocket message")
        msg = await ws.receive(timeout=remaining)
        if msg.type == WSMsgType.PING:
            await ws.pong()
            continue
        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
            raise AssertionError("WebSocket closed while waiting for message")
        if msg.type == WSMsgType.ERROR:
            raise AssertionError(f"WebSocket error while waiting for message: {ws.exception()}")
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            payload = json.loads(msg.data)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("t") == "ping":
            await ws.send_json({"v": 1, "t": "pong", "id": payload.get("id")})
            continue
        if isinstance(payload, dict):
            return payload


async def _ws_recv_until(ws, *, timeout_s: float, predicate):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        payload = await _ws_receive_payload(ws, deadline=deadline)
        if predicate(payload):
            return payload


async def _ws_open_session(client: TestClient, device_id: str, auth_token: str):
    ws = await client.ws_connect("/v1/ws")
    await ws.send_json(
        {
            "v": 1,
            "t": "session.start",
            "id": f"start_{device_id}",
            "body": {"auth_token": auth_token, "device_id": device_id},
        }
    )
    await _ws_recv_until(
        ws,
        timeout_s=1.0,
        predicate=lambda payload: payload.get("t") == "session.ready",
    )
    return ws


async def _ws_subscribe(ws, *, conv_id: str, from_seq: int) -> None:
    await ws.send_json(
        {
            "v": 1,
            "t": "conv.subscribe",
            "id": f"sub_{conv_id}",
            "body": {"conv_id": conv_id, "from_seq": from_seq},
        }
    )


async def _ws_wait_for_ack(ws, *, request_id: str, timeout_s: float) -> int:
    payload = await _ws_recv_until(
        ws,
        timeout_s=timeout_s,
        predicate=lambda message: message.get("t") == "conv.acked" and message.get("id") == request_id,
    )
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("seq"), int):
        raise AssertionError(f"Unexpected ack payload: {payload}")
    return body["seq"]


async def _ws_wait_for_event(ws, *, conv_id: str, expected_seq: int, timeout_s: float) -> dict:
    payload = await _ws_recv_until(
        ws,
        timeout_s=timeout_s,
        predicate=lambda message: message.get("t") == "conv.event"
        and isinstance(message.get("body"), dict)
        and message["body"].get("conv_id") == conv_id
        and message["body"].get("seq") == expected_seq,
    )
    return payload


async def _ws_assert_no_conv_event(ws, *, conv_id: str, timeout_s: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        try:
            payload = await _ws_receive_payload(ws, deadline=deadline)
        except asyncio.TimeoutError:
            return
        if payload.get("t") != "conv.event":
            continue
        body = payload.get("body")
        if not isinstance(body, dict):
            continue
        if body.get("conv_id") == conv_id:
            raise AssertionError(f"Unexpected conv.event rebroadcast: {payload}")


class Phase5CoexistLiveMlsFlowTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness_bin = ensure_harness_binary(timeout_s=120.0)
        cls.harness_env = make_harness_env()
        cls.harness_timeout = 10.0

    async def asyncSetUp(self) -> None:
        db_file = tempfile.NamedTemporaryFile(delete=False)
        db_file.close()
        self.app = create_app(db_path=db_file.name, ping_interval_s=3600)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()

    async def _run_harness(self, *args: str) -> str:
        try:
            proc = await asyncio.wait_for(
                asyncio.to_thread(
                    run_harness,
                    args,
                    harness_bin=self.harness_bin,
                    cwd=HARNESS_DIR,
                    env=self.harness_env,
                    timeout_s=self.harness_timeout,
                ),
                timeout=self.harness_timeout + 2.0,
            )
        except (asyncio.TimeoutError, TimeoutError, subprocess.TimeoutExpired):
            self.fail(f"mls-harness {' '.join(args)} timed out after {self.harness_timeout} seconds")

        if proc.returncode != 0:
            self.fail(
                f"mls-harness {' '.join(args)} failed with code {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}\n"
            )
        return proc.stdout.strip()

    async def _start_session_http(self, *, auth_token: str, device_id: str) -> dict:
        resp = await self.client.post(
            "/v1/session/start",
            json={"auth_token": auth_token, "device_id": device_id},
        )
        self.assertEqual(resp.status, 200)
        return await resp.json()

    async def _create_room(self, session_token: str, conv_id: str) -> None:
        resp = await self.client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _invite_member(self, session_token: str, conv_id: str, member: str) -> None:
        resp = await self.client.post(
            "/v1/rooms/invite",
            json={"conv_id": conv_id, "members": [member]},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _publish_keypackages(self, session_token: str, device_id: str, keypackages: list[str]) -> None:
        resp = await self.client.post(
            "/v1/keypackages",
            json={"device_id": device_id, "keypackages": keypackages},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _fetch_keypackages(self, session_token: str, user_id: str, count: int) -> list[str]:
        resp = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": user_id, "count": count},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        return body["keypackages"]

    async def test_live_mls_flow_dm_and_room_interleaved(self) -> None:
        conv_ids = {"dm": "conv_dm_live", "room": "conv_room_live"}
        group_ids = {
            key: base64.b64encode(conv_id.encode("utf-8")).decode("utf-8")
            for key, conv_id in conv_ids.items()
        }

        alice_auth = "auth-alice"
        bob_auth = "auth-bob"
        alice_ready = await self._start_session_http(auth_token=alice_auth, device_id="dev-alice")
        bob_ready = await self._start_session_http(auth_token=bob_auth, device_id="dev-bob")

        for conv_id in conv_ids.values():
            await self._create_room(alice_ready["session_token"], conv_id)
            await self._invite_member(alice_ready["session_token"], conv_id, bob_ready["user_id"])

        alice_ws = await _ws_open_session(self.client, "dev-alice", alice_auth)
        bob_ws = await _ws_open_session(self.client, "dev-bob", bob_auth)
        for conv_id in conv_ids.values():
            await _ws_subscribe(alice_ws, conv_id=conv_id, from_seq=1)
            await _ws_subscribe(bob_ws, conv_id=conv_id, from_seq=1)

        expected_seq = {"dm": 1, "room": 1}

        with (
            tempfile.TemporaryDirectory(prefix="alice-dm-") as alice_dm_dir,
            tempfile.TemporaryDirectory(prefix="bob-dm-") as bob_dm_dir,
            tempfile.TemporaryDirectory(prefix="alice-room-") as alice_room_dir,
            tempfile.TemporaryDirectory(prefix="bob-room-") as bob_room_dir,
            tempfile.TemporaryDirectory(prefix="room-guest-") as guest_room_dir,
        ):
            alice_dm_dir = Path(alice_dm_dir)
            bob_dm_dir = Path(bob_dm_dir)
            alice_room_dir = Path(alice_room_dir)
            bob_room_dir = Path(bob_room_dir)
            guest_room_dir = Path(guest_room_dir)

            alice_dm_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(alice_dm_dir),
                "--name",
                "alice-dm",
                "--seed",
                "12001",
            )
            bob_dm_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(bob_dm_dir),
                "--name",
                "bob-dm",
                "--seed",
                "12002",
            )

            await self._publish_keypackages(
                alice_ready["session_token"],
                "dev-alice",
                [alice_dm_kp],
            )
            await self._publish_keypackages(
                bob_ready["session_token"],
                "dev-bob",
                [bob_dm_kp],
            )

            bob_keypackages = await self._fetch_keypackages(
                alice_ready["session_token"],
                bob_ready["user_id"],
                1,
            )
            self.assertEqual(len(bob_keypackages), 1)
            bob_dm_kp_fetch = bob_keypackages[0]

            dm_init_output = await self._run_harness(
                "dm-init",
                "--state-dir",
                str(alice_dm_dir),
                "--peer-keypackage",
                bob_dm_kp_fetch,
                "--group-id",
                group_ids["dm"],
                "--seed",
                "22001",
            )
            dm_init_payload = json.loads(dm_init_output)

            dm_welcome_env = dm_envelope.pack(1, dm_init_payload["welcome"])
            dm_welcome_msg_id = _msg_id_for_env(dm_welcome_env)
            await alice_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "dm-welcome",
                    "body": {
                        "conv_id": conv_ids["dm"],
                        "msg_id": dm_welcome_msg_id,
                        "env": dm_welcome_env,
                    },
                }
            )
            dm_welcome_seq = await _ws_wait_for_ack(alice_ws, request_id="dm-welcome", timeout_s=2.0)
            self.assertEqual(dm_welcome_seq, expected_seq["dm"])

            alice_dm_welcome_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )
            bob_dm_welcome_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )
            for event in (alice_dm_welcome_event, bob_dm_welcome_event):
                self.assertEqual(event["body"]["msg_id"], _msg_id_for_env(event["body"]["env"]))

            dm_welcome_kind, dm_welcome_payload = dm_envelope.unpack(bob_dm_welcome_event["body"]["env"])
            self.assertEqual(dm_welcome_kind, 1)
            await self._run_harness(
                "dm-join",
                "--state-dir",
                str(bob_dm_dir),
                "--welcome",
                dm_welcome_payload,
            )

            alice_room_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(alice_room_dir),
                "--name",
                "alice-room",
                "--seed",
                "13001",
            )
            bob_room_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(bob_room_dir),
                "--name",
                "bob-room",
                "--seed",
                "13002",
            )
            guest_room_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(guest_room_dir),
                "--name",
                "room-guest",
                "--seed",
                "13003",
            )

            await self._publish_keypackages(
                alice_ready["session_token"],
                "dev-alice",
                [alice_room_kp],
            )
            await self._publish_keypackages(
                bob_ready["session_token"],
                "dev-bob",
                [bob_room_kp],
            )

            bob_room_keypackages = await self._fetch_keypackages(
                alice_ready["session_token"],
                bob_ready["user_id"],
                1,
            )
            self.assertEqual(len(bob_room_keypackages), 1)
            bob_room_kp_fetch = bob_room_keypackages[0]

            room_init_output = await self._run_harness(
                "group-init",
                "--state-dir",
                str(alice_room_dir),
                "--peer-keypackage",
                bob_room_kp_fetch,
                "--peer-keypackage",
                guest_room_kp,
                "--group-id",
                group_ids["room"],
                "--seed",
                "23001",
            )
            room_init_payload = json.loads(room_init_output)

            room_welcome_env = dm_envelope.pack(1, room_init_payload["welcome"])
            room_welcome_msg_id = _msg_id_for_env(room_welcome_env)
            await alice_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "room-welcome",
                    "body": {
                        "conv_id": conv_ids["room"],
                        "msg_id": room_welcome_msg_id,
                        "env": room_welcome_env,
                    },
                }
            )
            room_welcome_seq = await _ws_wait_for_ack(alice_ws, request_id="room-welcome", timeout_s=2.0)
            self.assertEqual(room_welcome_seq, expected_seq["room"])

            alice_room_welcome_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )
            bob_room_welcome_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )
            for event in (alice_room_welcome_event, bob_room_welcome_event):
                self.assertEqual(event["body"]["msg_id"], _msg_id_for_env(event["body"]["env"]))

            room_welcome_kind, room_welcome_payload = dm_envelope.unpack(bob_room_welcome_event["body"]["env"])
            self.assertEqual(room_welcome_kind, 1)
            await self._run_harness(
                "dm-join",
                "--state-dir",
                str(bob_room_dir),
                "--welcome",
                room_welcome_payload,
            )

            expected_seq["dm"] += 1
            dm_commit_env = dm_envelope.pack(2, dm_init_payload["commit"])
            await alice_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "dm-commit",
                    "body": {
                        "conv_id": conv_ids["dm"],
                        "msg_id": _msg_id_for_env(dm_commit_env),
                        "env": dm_commit_env,
                    },
                }
            )
            dm_commit_seq = await _ws_wait_for_ack(alice_ws, request_id="dm-commit", timeout_s=2.0)
            self.assertEqual(dm_commit_seq, expected_seq["dm"])

            alice_dm_commit_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )
            bob_dm_commit_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )

            dm_commit_kind, dm_commit_payload = dm_envelope.unpack(alice_dm_commit_event["body"]["env"])
            self.assertEqual(dm_commit_kind, 2)
            await self._run_harness(
                "dm-commit-apply",
                "--state-dir",
                str(alice_dm_dir),
                "--commit",
                dm_commit_payload,
            )

            _, dm_commit_payload_bob = dm_envelope.unpack(bob_dm_commit_event["body"]["env"])
            await self._run_harness(
                "dm-commit-apply",
                "--state-dir",
                str(bob_dm_dir),
                "--commit",
                dm_commit_payload_bob,
            )

            expected_seq["room"] += 1
            room_commit_env = dm_envelope.pack(2, room_init_payload["commit"])
            await alice_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "room-commit",
                    "body": {
                        "conv_id": conv_ids["room"],
                        "msg_id": _msg_id_for_env(room_commit_env),
                        "env": room_commit_env,
                    },
                }
            )
            room_commit_seq = await _ws_wait_for_ack(alice_ws, request_id="room-commit", timeout_s=2.0)
            self.assertEqual(room_commit_seq, expected_seq["room"])

            alice_room_commit_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )
            bob_room_commit_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )

            room_commit_kind, room_commit_payload = dm_envelope.unpack(alice_room_commit_event["body"]["env"])
            self.assertEqual(room_commit_kind, 2)
            await self._run_harness(
                "dm-commit-apply",
                "--state-dir",
                str(alice_room_dir),
                "--commit",
                room_commit_payload,
            )

            _, room_commit_payload_bob = dm_envelope.unpack(bob_room_commit_event["body"]["env"])
            await self._run_harness(
                "dm-commit-apply",
                "--state-dir",
                str(bob_room_dir),
                "--commit",
                room_commit_payload_bob,
            )

            expected_seq["dm"] += 1
            dm_app_cipher = await self._run_harness(
                "dm-encrypt",
                "--state-dir",
                str(alice_dm_dir),
                "--plaintext",
                "dm:hello-from-alice",
            )
            dm_app_env = dm_envelope.pack(3, dm_app_cipher)
            dm_app_msg_id = _msg_id_for_env(dm_app_env)
            await alice_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "dm-app-alice",
                    "body": {
                        "conv_id": conv_ids["dm"],
                        "msg_id": dm_app_msg_id,
                        "env": dm_app_env,
                    },
                }
            )
            dm_app_seq = await _ws_wait_for_ack(alice_ws, request_id="dm-app-alice", timeout_s=2.0)
            self.assertEqual(dm_app_seq, expected_seq["dm"])

            bob_dm_app_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )
            alice_dm_app_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )
            self.assertEqual(bob_dm_app_event["body"]["msg_id"], _msg_id_for_env(bob_dm_app_event["body"]["env"]))
            self.assertEqual(alice_dm_app_event["body"]["msg_id"], _msg_id_for_env(alice_dm_app_event["body"]["env"]))
            _, bob_dm_cipher = dm_envelope.unpack(bob_dm_app_event["body"]["env"])
            bob_dm_plaintext = await self._run_harness(
                "dm-decrypt",
                "--state-dir",
                str(bob_dm_dir),
                "--ciphertext",
                bob_dm_cipher,
            )
            self.assertEqual(bob_dm_plaintext, "dm:hello-from-alice")

            expected_seq["room"] += 1
            room_app_cipher = await self._run_harness(
                "dm-encrypt",
                "--state-dir",
                str(alice_room_dir),
                "--plaintext",
                "room:hello-from-alice",
            )
            room_app_env = dm_envelope.pack(3, room_app_cipher)
            await alice_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "room-app-alice",
                    "body": {
                        "conv_id": conv_ids["room"],
                        "msg_id": _msg_id_for_env(room_app_env),
                        "env": room_app_env,
                    },
                }
            )
            room_app_seq = await _ws_wait_for_ack(alice_ws, request_id="room-app-alice", timeout_s=2.0)
            self.assertEqual(room_app_seq, expected_seq["room"])

            bob_room_app_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )
            alice_room_app_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )
            self.assertEqual(
                bob_room_app_event["body"]["msg_id"], _msg_id_for_env(bob_room_app_event["body"]["env"])
            )
            self.assertEqual(
                alice_room_app_event["body"]["msg_id"], _msg_id_for_env(alice_room_app_event["body"]["env"])
            )
            _, bob_room_cipher = dm_envelope.unpack(bob_room_app_event["body"]["env"])
            bob_room_plaintext = await self._run_harness(
                "dm-decrypt",
                "--state-dir",
                str(bob_room_dir),
                "--ciphertext",
                bob_room_cipher,
            )
            self.assertEqual(bob_room_plaintext, "room:hello-from-alice")

            expected_seq["dm"] += 1
            dm_reply_cipher = await self._run_harness(
                "dm-encrypt",
                "--state-dir",
                str(bob_dm_dir),
                "--plaintext",
                "dm:reply-from-bob",
            )
            dm_reply_env = dm_envelope.pack(3, dm_reply_cipher)
            await bob_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "dm-app-bob",
                    "body": {
                        "conv_id": conv_ids["dm"],
                        "msg_id": _msg_id_for_env(dm_reply_env),
                        "env": dm_reply_env,
                    },
                }
            )
            dm_reply_seq = await _ws_wait_for_ack(bob_ws, request_id="dm-app-bob", timeout_s=2.0)
            self.assertEqual(dm_reply_seq, expected_seq["dm"])

            alice_dm_reply_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )
            bob_dm_reply_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["dm"],
                expected_seq=expected_seq["dm"],
                timeout_s=2.0,
            )
            self.assertEqual(
                alice_dm_reply_event["body"]["msg_id"], _msg_id_for_env(alice_dm_reply_event["body"]["env"])
            )
            self.assertEqual(
                bob_dm_reply_event["body"]["msg_id"], _msg_id_for_env(bob_dm_reply_event["body"]["env"])
            )
            _, alice_dm_cipher = dm_envelope.unpack(alice_dm_reply_event["body"]["env"])
            alice_dm_plaintext = await self._run_harness(
                "dm-decrypt",
                "--state-dir",
                str(alice_dm_dir),
                "--ciphertext",
                alice_dm_cipher,
            )
            self.assertEqual(alice_dm_plaintext, "dm:reply-from-bob")

            expected_seq["room"] += 1
            room_reply_cipher = await self._run_harness(
                "dm-encrypt",
                "--state-dir",
                str(bob_room_dir),
                "--plaintext",
                "room:reply-from-bob",
            )
            room_reply_env = dm_envelope.pack(3, room_reply_cipher)
            await bob_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "room-app-bob",
                    "body": {
                        "conv_id": conv_ids["room"],
                        "msg_id": _msg_id_for_env(room_reply_env),
                        "env": room_reply_env,
                    },
                }
            )
            room_reply_seq = await _ws_wait_for_ack(bob_ws, request_id="room-app-bob", timeout_s=2.0)
            self.assertEqual(room_reply_seq, expected_seq["room"])

            alice_room_reply_event = await _ws_wait_for_event(
                alice_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )
            bob_room_reply_event = await _ws_wait_for_event(
                bob_ws,
                conv_id=conv_ids["room"],
                expected_seq=expected_seq["room"],
                timeout_s=2.0,
            )
            self.assertEqual(
                alice_room_reply_event["body"]["msg_id"], _msg_id_for_env(alice_room_reply_event["body"]["env"])
            )
            self.assertEqual(
                bob_room_reply_event["body"]["msg_id"], _msg_id_for_env(bob_room_reply_event["body"]["env"])
            )
            _, alice_room_cipher = dm_envelope.unpack(alice_room_reply_event["body"]["env"])
            alice_room_plaintext = await self._run_harness(
                "dm-decrypt",
                "--state-dir",
                str(alice_room_dir),
                "--ciphertext",
                alice_room_cipher,
            )
            self.assertEqual(alice_room_plaintext, "room:reply-from-bob")

            await alice_ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": "dm-app-alice-retry",
                    "body": {
                        "conv_id": conv_ids["dm"],
                        "msg_id": dm_app_msg_id,
                        "env": dm_app_env,
                    },
                }
            )
            dm_retry_seq = await _ws_wait_for_ack(alice_ws, request_id="dm-app-alice-retry", timeout_s=2.0)
            self.assertEqual(dm_retry_seq, dm_app_seq)

            await _ws_assert_no_conv_event(alice_ws, conv_id=conv_ids["dm"], timeout_s=0.4)
            await _ws_assert_no_conv_event(bob_ws, conv_id=conv_ids["dm"], timeout_s=0.4)

        await alice_ws.close()
        await bob_ws.close()


if __name__ == "__main__":
    unittest.main()
