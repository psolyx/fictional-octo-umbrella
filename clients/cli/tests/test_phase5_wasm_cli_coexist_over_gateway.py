import asyncio
import contextlib
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


class Phase5WasmCliCoexistOverGatewayTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node_bin = shutil.which("node")
        if not cls.node_bin:
            raise unittest.SkipTest("Node runtime not available")
        ws_check = subprocess.run(
            [cls.node_bin, "-e", "process.exit(typeof WebSocket === 'function' ? 0 : 1)"],
            check=False,
            capture_output=True,
            text=True,
        )
        if ws_check.returncode != 0:
            raise unittest.SkipTest("Node WebSocket not available")

        cls.harness_bin = ensure_harness_binary(timeout_s=120.0)
        cls.harness_env = make_harness_env()
        cls.harness_timeout = 10.0
        cls.repo_root = ROOT_DIR
        cls.node_script = cls.repo_root / "clients" / "web" / "tools" / "phase5_wasm_ws_client.js"

        build_script = cls.repo_root / "tools" / "mls_harness" / "build_wasm.sh"
        proc = subprocess.run(
            ["bash", str(build_script)],
            check=False,
            capture_output=True,
            text=True,
            cwd=cls.repo_root,
            env=make_harness_env(),
            timeout=120.0,
        )
        if proc.returncode != 0:
            raise AssertionError(
                "Failed to build wasm harness:\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}\n"
            )

    async def asyncSetUp(self) -> None:
        db_file = tempfile.NamedTemporaryFile(delete=False)
        db_file.close()
        self.app = create_app(db_path=db_file.name, ping_interval_s=3600)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.base_url = str(self.server.make_url(""))

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

    async def _run_bob_flow(
        self,
        ws,
        *,
        conv_ids: dict,
        dm_state_dir: Path,
        room_state_dir: Path,
        dm_plaintext: str,
        room_plaintext: str,
        dm_reply: str,
        room_reply: str,
    ) -> None:
        conv_by_id = {conv_ids["dm"]: "dm", conv_ids["room"]: "room"}
        state_dirs = {"dm": dm_state_dir, "room": room_state_dir}
        alice_plaintexts = {"dm": dm_plaintext, "room": room_plaintext}
        reply_plaintexts = {"dm": dm_reply, "room": room_reply}
        stages = {"dm": "welcome", "room": "welcome"}
        expected_seq = {"dm": 1, "room": 1}

        deadline = asyncio.get_running_loop().time() + 15.0
        while not all(stage == "done" for stage in stages.values()):
            payload = await _ws_receive_payload(ws, deadline=deadline)
            if payload.get("t") != "conv.event":
                continue
            body = payload.get("body")
            if not isinstance(body, dict):
                continue
            conv_id = body.get("conv_id")
            if conv_id not in conv_by_id:
                continue
            conv_key = conv_by_id[conv_id]
            seq = body.get("seq")
            if seq != expected_seq[conv_key]:
                raise AssertionError(f"Unexpected seq {seq} for {conv_key}")
            env_b64 = body.get("env")
            msg_id = body.get("msg_id")
            if not isinstance(env_b64, str) or not isinstance(msg_id, str):
                raise AssertionError("Missing env or msg_id")
            if _msg_id_for_env(env_b64) != msg_id:
                raise AssertionError("msg_id does not match env bytes")
            kind, payload_b64 = dm_envelope.unpack(env_b64)

            if stages[conv_key] == "welcome":
                if kind != 1:
                    raise AssertionError("Expected welcome envelope")
                await self._run_harness(
                    "dm-join",
                    "--state-dir",
                    str(state_dirs[conv_key]),
                    "--welcome",
                    payload_b64,
                )
                stages[conv_key] = "commit"
                expected_seq[conv_key] += 1
                continue

            if stages[conv_key] == "commit":
                if kind != 2:
                    raise AssertionError("Expected commit envelope")
                await self._run_harness(
                    "dm-commit-apply",
                    "--state-dir",
                    str(state_dirs[conv_key]),
                    "--commit",
                    payload_b64,
                )
                stages[conv_key] = "app"
                expected_seq[conv_key] += 1
                continue

            if stages[conv_key] == "app":
                if kind != 3:
                    raise AssertionError("Expected app envelope")
                plaintext = await self._run_harness(
                    "dm-decrypt",
                    "--state-dir",
                    str(state_dirs[conv_key]),
                    "--ciphertext",
                    payload_b64,
                )
                self.assertTrue(plaintext == alice_plaintexts[conv_key])
                expected_seq[conv_key] += 1

                ciphertext = await self._run_harness(
                    "dm-encrypt",
                    "--state-dir",
                    str(state_dirs[conv_key]),
                    "--plaintext",
                    reply_plaintexts[conv_key],
                )
                reply_env = dm_envelope.pack(3, ciphertext)
                reply_msg_id = _msg_id_for_env(reply_env)
                request_id = f"reply_{conv_key}"
                await ws.send_json(
                    {
                        "v": 1,
                        "t": "conv.send",
                        "id": request_id,
                        "body": {"conv_id": conv_id, "msg_id": reply_msg_id, "env": reply_env},
                    }
                )
                ack_seq = await _ws_wait_for_ack(ws, request_id=request_id, timeout_s=2.0)
                self.assertEqual(ack_seq, expected_seq[conv_key])
                stages[conv_key] = "reply"
                continue

            if stages[conv_key] == "reply":
                if kind != 3:
                    raise AssertionError("Expected reply envelope")
                plaintext = await self._run_harness(
                    "dm-decrypt",
                    "--state-dir",
                    str(state_dirs[conv_key]),
                    "--ciphertext",
                    payload_b64,
                )
                self.assertTrue(plaintext == reply_plaintexts[conv_key])
                stages[conv_key] = "done"
                expected_seq[conv_key] += 1
                continue

            raise AssertionError("Unexpected stage")

    async def test_phase5_wasm_cli_coexist_over_gateway(self) -> None:
        conv_ids = {"dm": "conv_phase5_wasm_dm", "room": "conv_phase5_wasm_room"}
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

        ws_url = str(self.server.make_url("/v1/ws"))
        if ws_url.startswith("http"):
            ws_url = "ws" + ws_url[4:]

        bob_ws = await _ws_open_session(self.client, "dev-bob-cli", bob_auth)
        for conv_id in conv_ids.values():
            await _ws_subscribe(bob_ws, conv_id=conv_id, from_seq=1)

        with (
            tempfile.TemporaryDirectory(prefix="bob-dm-") as bob_dm_dir,
            tempfile.TemporaryDirectory(prefix="bob-room-") as bob_room_dir,
            tempfile.TemporaryDirectory(prefix="room-guest-") as guest_room_dir,
        ):
            bob_dm_dir = Path(bob_dm_dir)
            bob_room_dir = Path(bob_room_dir)
            guest_room_dir = Path(guest_room_dir)

            bob_dm_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(bob_dm_dir),
                "--name",
                "bob-dm",
                "--seed",
                "41001",
            )
            bob_room_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(bob_room_dir),
                "--name",
                "bob-room",
                "--seed",
                "41002",
            )
            guest_room_kp = await self._run_harness(
                "dm-keypackage",
                "--state-dir",
                str(guest_room_dir),
                "--name",
                "room-guest",
                "--seed",
                "41003",
            )

            node_payload = {
                "ws_url": ws_url,
                "auth_token": alice_auth,
                "device_id": "dev-alice-wasm",
                "dm": {
                    "conv_id": conv_ids["dm"],
                    "group_id_b64": group_ids["dm"],
                    "bob_keypackage_b64": bob_dm_kp,
                    "participant_name": "alice-dm",
                    "participant_seed": 51001,
                    "init_seed": 52001,
                    "app_plaintext": "phase5-dm-hello",
                    "reply_plaintext": "phase5-dm-reply",
                },
                "room": {
                    "conv_id": conv_ids["room"],
                    "group_id_b64": group_ids["room"],
                    "bob_keypackage_b64": bob_room_kp,
                    "guest_keypackage_b64": guest_room_kp,
                    "participant_name": "alice-room",
                    "participant_seed": 51002,
                    "init_seed": 52002,
                    "app_plaintext": "phase5-room-hello",
                    "reply_plaintext": "phase5-room-reply",
                },
            }

            node_env = dict(os.environ)
            node_process = await asyncio.create_subprocess_exec(
                self.node_bin,
                str(self.node_script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.repo_root,
                env=node_env,
            )
            assert node_process.stdin is not None
            node_process.stdin.write(json.dumps(node_payload).encode("utf-8"))
            await node_process.stdin.drain()
            node_process.stdin.close()

            bob_task = asyncio.create_task(
                self._run_bob_flow(
                    bob_ws,
                    conv_ids=conv_ids,
                    dm_state_dir=bob_dm_dir,
                    room_state_dir=bob_room_dir,
                    dm_plaintext=node_payload["dm"]["app_plaintext"],
                    room_plaintext=node_payload["room"]["app_plaintext"],
                    dm_reply=node_payload["dm"]["reply_plaintext"],
                    room_reply=node_payload["room"]["reply_plaintext"],
                )
            )
            try:
                stdout, stderr = await asyncio.wait_for(node_process.communicate(), timeout=20.0)
            except asyncio.TimeoutError:
                node_process.kill()
                stdout, stderr = await node_process.communicate()
                self.fail("Node process timed out")

            if node_process.returncode != 0:
                bob_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await bob_task
                self.fail(
                    "Node wasm client failed:\n"
                    f"stdout:\n{stdout.decode('utf-8', errors='ignore')}\n"
                    f"stderr:\n{stderr.decode('utf-8', errors='ignore')}\n"
                )

            await asyncio.wait_for(bob_task, timeout=20.0)

        await bob_ws.close()


if __name__ == "__main__":
    unittest.main()
