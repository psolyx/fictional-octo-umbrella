import asyncio
import base64
import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional, Tuple

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway MLS DM tests")

from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway MLS DM tests, found {_installed_aiohttp}"
    )

from gateway.ws_transport import create_app

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from mls_harness_util import HARNESS_DIR, ensure_harness_binary, make_harness_env, run_harness


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


def pack_dm_env(kind: int, payload_b64: str) -> str:
    env_bytes = bytes([kind]) + base64.b64decode(payload_b64, validate=True)
    return base64.b64encode(env_bytes).decode("utf-8")


def unpack_dm_env(env_b64: str) -> Tuple[int, str]:
    env_bytes = base64.b64decode(env_b64, validate=True)
    kind = env_bytes[0]
    payload_b64 = base64.b64encode(env_bytes[1:]).decode("utf-8")
    return kind, payload_b64


def msg_id_for_env(env_b64: str) -> str:
    return hashlib.sha256(base64.b64decode(env_b64, validate=True)).hexdigest()


class MlsDmOverDsTests(unittest.IsolatedAsyncioTestCase):
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

    async def _start_session_http(self, *, auth_token: str, device_id: str):
        resp = await self.client.post(
            "/v1/session/start",
            json={"auth_token": auth_token, "device_id": device_id},
        )
        self.assertEqual(resp.status, 200)
        return await resp.json()

    async def _create_room(self, session_token: str, conv_id: str):
        resp = await self.client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _invite_member(self, session_token: str, conv_id: str, member: str):
        resp = await self.client.post(
            "/v1/rooms/invite",
            json={"conv_id": conv_id, "members": [member]},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _post_inbox(self, session_token: str, frame: dict):
        resp = await self.client.post(
            "/v1/inbox",
            json=frame,
            headers={"Authorization": f"Bearer {session_token}"},
        )
        return resp

    async def _publish_keypackages(self, session_token: str, device_id: str, keypackages: list[str]):
        resp = await self.client.post(
            "/v1/keypackages",
            json={"device_id": device_id, "keypackages": keypackages},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _fetch_keypackages(self, session_token: str, user_id: str, count: int = 1):
        resp = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": user_id, "count": count},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        return body["keypackages"]

    async def _run_harness_raw(self, env: Dict[str, str], *args: str) -> Tuple[Optional[int], str, str]:
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
            return None, "", "mls-harness timed out"

        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    async def _run_harness(self, env: Dict[str, str], *args: str) -> str:
        rc, stdout, stderr = await self._run_harness_raw(env, *args)
        if rc is None:
            self.fail(f"mls-harness {' '.join(args)} timed out after {self.harness_timeout} seconds")
        if rc != 0:
            self.fail(
                f"mls-harness {' '.join(args)} failed with code {rc}\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}\n"
            )
        return stdout

    async def test_dm_roundtrip_over_ds(self):
        env: Dict[str, str] = dict(self.harness_env)

        initiator_auth = "Bearer initiator"
        joiner_auth = "Bearer joiner"
        conv_id = "dm-conv-1"

        ready_initiator = await self._start_session_http(auth_token=initiator_auth, device_id="dev-init")
        ready_joiner = await self._start_session_http(auth_token=joiner_auth, device_id="dev-join")

        await self._create_room(ready_initiator["session_token"], conv_id)
        await self._invite_member(ready_initiator["session_token"], conv_id, ready_joiner["user_id"])

        with tempfile.TemporaryDirectory() as init_dir, tempfile.TemporaryDirectory() as join_dir:
            initiator_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", init_dir, "--name", "initiator", "--seed", "9001"
            )
            joiner_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", join_dir, "--name", "joiner", "--seed", "9002"
            )

            await self._publish_keypackages(ready_initiator["session_token"], "dev-init", [initiator_kp])
            await self._publish_keypackages(ready_joiner["session_token"], "dev-join", [joiner_kp])

            fetched = await self._fetch_keypackages(ready_initiator["session_token"], ready_joiner["user_id"], 1)
            self.assertEqual(len(fetched), 1)

            init_output = await self._run_harness(
                env,
                "dm-init",
                "--state-dir",
                init_dir,
                "--peer-keypackage",
                fetched[0],
                "--group-id",
                "ZG0tZ3JvdXA=",
                "--seed",
                "4242",
            )
            init_payload = json.loads(init_output)

            initiator_sse = await self.client.get(
                "/v1/sse",
                params={"conv_id": conv_id, "from_seq": "1"},
                headers={"Authorization": f"Bearer {ready_initiator['session_token']}"},
            )
            self.assertEqual(initiator_sse.status, 200)

            joiner_sse = await self.client.get(
                "/v1/sse",
                params={"conv_id": conv_id, "from_seq": "1"},
                headers={"Authorization": f"Bearer {ready_joiner['session_token']}"},
            )
            self.assertEqual(joiner_sse.status, 200)

            expected_seq = 1
            welcome_env = pack_dm_env(1, init_payload["welcome"])
            welcome_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "welcome1",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(welcome_env),
                    "env": welcome_env,
                },
            }
            welcome_resp = await self._post_inbox(ready_initiator["session_token"], welcome_frame)
            self.assertEqual(welcome_resp.status, 200)
            welcome_ack = await welcome_resp.json()
            self.assertEqual(welcome_ack["seq"], expected_seq)

            evt_type_init, welcome_evt_init = await read_sse_event(initiator_sse)
            evt_type_join, welcome_evt_join = await read_sse_event(joiner_sse)
            self.assertEqual(evt_type_init, "conv.event")
            self.assertEqual(evt_type_join, "conv.event")
            self.assertEqual(welcome_evt_init["body"]["seq"], expected_seq)
            self.assertEqual(welcome_evt_join["body"]["seq"], expected_seq)
            self.assertEqual(
                welcome_evt_init["body"]["msg_id"], msg_id_for_env(welcome_evt_init["body"]["env"])
            )
            self.assertEqual(
                welcome_evt_join["body"]["msg_id"], msg_id_for_env(welcome_evt_join["body"]["env"])
            )
            _, welcome_payload = unpack_dm_env(welcome_evt_join["body"]["env"])
            await self._run_harness(
                env, "dm-join", "--state-dir", join_dir, "--welcome", welcome_payload
            )

            expected_seq += 1
            commit_env = pack_dm_env(2, init_payload["commit"])
            commit_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "commit1",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(commit_env),
                    "env": commit_env,
                },
            }
            commit_resp = await self._post_inbox(ready_initiator["session_token"], commit_frame)
            self.assertEqual(commit_resp.status, 200)
            commit_ack = await commit_resp.json()
            self.assertEqual(commit_ack["seq"], expected_seq)

            retry_resp = await self._post_inbox(ready_initiator["session_token"], commit_frame)
            self.assertEqual(retry_resp.status, 200)
            retry_ack = await retry_resp.json()
            self.assertEqual(retry_ack["seq"], expected_seq)

            evt_type_init_commit, commit_evt_init = await read_sse_event(initiator_sse)
            evt_type_join_commit, commit_evt_join = await read_sse_event(joiner_sse)
            self.assertEqual(evt_type_init_commit, "conv.event")
            self.assertEqual(evt_type_join_commit, "conv.event")
            self.assertEqual(commit_evt_init["body"]["seq"], expected_seq)
            self.assertEqual(commit_evt_join["body"]["seq"], expected_seq)
            self.assertEqual(
                commit_evt_init["body"]["msg_id"], msg_id_for_env(commit_evt_init["body"]["env"])
            )
            self.assertEqual(
                commit_evt_join["body"]["msg_id"], msg_id_for_env(commit_evt_join["body"]["env"])
            )
            _, join_commit_payload = unpack_dm_env(commit_evt_join["body"]["env"])
            _, init_commit_payload = unpack_dm_env(commit_evt_init["body"]["env"])
            await self._run_harness(
                env,
                "dm-commit-apply",
                "--state-dir",
                join_dir,
                "--commit",
                join_commit_payload,
            )
            await self._run_harness(
                env,
                "dm-commit-apply",
                "--state-dir",
                init_dir,
                "--commit",
                init_commit_payload,
            )

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(read_sse_event(joiner_sse), timeout=0.2)

            expected_seq += 1
            retry_plaintext = "hello-once"
            retry_cipher = await self._run_harness(
                env, "dm-encrypt", "--state-dir", init_dir, "--plaintext", retry_plaintext
            )
            retry_env = pack_dm_env(3, retry_cipher)
            retry_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "app-retry",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(retry_env),
                    "env": retry_env,
                },
            }
            retry_resp1 = await self._post_inbox(ready_initiator["session_token"], retry_frame)
            self.assertEqual(retry_resp1.status, 200)
            retry_ack1 = await retry_resp1.json()
            self.assertEqual(retry_ack1["seq"], expected_seq)
            retry_resp2 = await self._post_inbox(ready_initiator["session_token"], retry_frame)
            self.assertEqual(retry_resp2.status, 200)
            retry_ack2 = await retry_resp2.json()
            self.assertEqual(retry_ack2["seq"], expected_seq)

            evt_type_init_retry, retry_evt_init = await read_sse_event(initiator_sse)
            evt_type_join_retry, retry_evt_join = await read_sse_event(joiner_sse)
            self.assertEqual(evt_type_init_retry, "conv.event")
            self.assertEqual(evt_type_join_retry, "conv.event")
            self.assertEqual(retry_evt_init["body"]["seq"], expected_seq)
            self.assertEqual(retry_evt_join["body"]["seq"], expected_seq)
            self.assertEqual(retry_evt_init["body"]["msg_id"], msg_id_for_env(retry_evt_init["body"]["env"]))
            self.assertEqual(retry_evt_join["body"]["msg_id"], msg_id_for_env(retry_evt_join["body"]["env"]))
            _, retry_payload = unpack_dm_env(retry_evt_join["body"]["env"])
            decrypted_retry = await self._run_harness(
                env,
                "dm-decrypt",
                "--state-dir",
                join_dir,
                "--ciphertext",
                retry_payload,
            )
            self.assertEqual(decrypted_retry, retry_plaintext)

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(read_sse_event(joiner_sse), timeout=0.2)

            expected_seq += 1

            async def send_and_confirm(
                sender_env: dict,
                sender_dir: str,
                sender_sse,
                receiver_sse,
                receiver_dir: str,
                msg_id: str,
                plaintext: str,
            ):
                nonlocal expected_seq
                ct = await self._run_harness(env, "dm-encrypt", "--state-dir", sender_dir, "--plaintext", plaintext)
                env_b64 = pack_dm_env(3, ct)
                frame_msg_id = msg_id_for_env(env_b64)
                frame = {
                    "v": 1,
                    "t": "conv.send",
                    "id": msg_id,
                    "body": {"conv_id": conv_id, "msg_id": frame_msg_id, "env": env_b64},
                }
                resp = await self._post_inbox(sender_env["session_token"], frame)
                self.assertEqual(resp.status, 200)
                ack = await resp.json()
                self.assertEqual(ack["seq"], expected_seq)

                evt_type_sender, sender_evt = await read_sse_event(sender_sse)
                evt_type_receiver, receiver_evt = await read_sse_event(receiver_sse)
                self.assertEqual(evt_type_sender, "conv.event")
                self.assertEqual(evt_type_receiver, "conv.event")
                self.assertEqual(sender_evt["body"]["seq"], expected_seq)
                self.assertEqual(receiver_evt["body"]["seq"], expected_seq)
                self.assertEqual(sender_evt["body"]["msg_id"], msg_id_for_env(sender_evt["body"]["env"]))
                self.assertEqual(receiver_evt["body"]["msg_id"], msg_id_for_env(receiver_evt["body"]["env"]))

                _, receiver_payload = unpack_dm_env(receiver_evt["body"]["env"])
                decrypted = await self._run_harness(
                    env,
                    "dm-decrypt",
                    "--state-dir",
                    receiver_dir,
                    "--ciphertext",
                    receiver_payload,
                )
                self.assertEqual(decrypted, plaintext)
                expected_seq += 1

            initiator_env = {"session_token": ready_initiator["session_token"], "state_dir": init_dir}
            joiner_env = {"session_token": ready_joiner["session_token"], "state_dir": join_dir}

            await send_and_confirm(
                initiator_env, init_dir, initiator_sse, joiner_sse, join_dir, "msg-1", "hi-joiner"
            )
            await send_and_confirm(
                joiner_env, join_dir, joiner_sse, initiator_sse, init_dir, "msg-2", "hi-initiator"
            )

            await initiator_sse.release()
            await joiner_sse.release()

    async def test_dm_multidevice_state_clone_all_decrypt(self):
        env: Dict[str, str] = dict(self.harness_env)

        initiator_auth = "Bearer initiator"
        joiner_auth = "Bearer joiner"
        conv_id = "dm-conv-1"

        ready_initiator = await self._start_session_http(auth_token=initiator_auth, device_id="dev-init")
        ready_joiner = await self._start_session_http(auth_token=joiner_auth, device_id="dev-join")

        await self._create_room(ready_initiator["session_token"], conv_id)
        await self._invite_member(ready_initiator["session_token"], conv_id, ready_joiner["user_id"])

        with tempfile.TemporaryDirectory() as init_dir, tempfile.TemporaryDirectory() as join_dir:
            initiator_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", init_dir, "--name", "initiator", "--seed", "9001"
            )
            joiner_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", join_dir, "--name", "joiner", "--seed", "9002"
            )

            await self._publish_keypackages(ready_initiator["session_token"], "dev-init", [initiator_kp])
            await self._publish_keypackages(ready_joiner["session_token"], "dev-join", [joiner_kp])

            fetched = await self._fetch_keypackages(ready_initiator["session_token"], ready_joiner["user_id"], 1)
            self.assertEqual(len(fetched), 1)

            init_output = await self._run_harness(
                env,
                "dm-init",
                "--state-dir",
                init_dir,
                "--peer-keypackage",
                fetched[0],
                "--group-id",
                "ZG0tZ3JvdXA=",
                "--seed",
                "4242",
            )
            init_payload = json.loads(init_output)

            initiator_sse = await self.client.get(
                "/v1/sse",
                params={"conv_id": conv_id, "from_seq": "1"},
                headers={"Authorization": f"Bearer {ready_initiator['session_token']}"},
            )
            self.assertEqual(initiator_sse.status, 200)

            joiner_sse = await self.client.get(
                "/v1/sse",
                params={"conv_id": conv_id, "from_seq": "1"},
                headers={"Authorization": f"Bearer {ready_joiner['session_token']}"},
            )
            self.assertEqual(joiner_sse.status, 200)

            expected_seq = 1
            welcome_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "welcome1",
                "body": {"conv_id": conv_id, "msg_id": "welcome", "env": init_payload["welcome"]},
            }
            welcome_resp = await self._post_inbox(ready_initiator["session_token"], welcome_frame)
            self.assertEqual(welcome_resp.status, 200)
            welcome_ack = await welcome_resp.json()
            self.assertEqual(welcome_ack["seq"], expected_seq)

            evt_type_init, welcome_evt_init = await read_sse_event(initiator_sse)
            evt_type_join, welcome_evt_join = await read_sse_event(joiner_sse)
            self.assertEqual(evt_type_init, "conv.event")
            self.assertEqual(evt_type_join, "conv.event")
            self.assertEqual(welcome_evt_init["body"]["seq"], expected_seq)
            self.assertEqual(welcome_evt_join["body"]["seq"], expected_seq)
            await self._run_harness(
                env, "dm-join", "--state-dir", join_dir, "--welcome", welcome_evt_join["body"]["env"]
            )

            expected_seq += 1
            commit_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "commit1",
                "body": {"conv_id": conv_id, "msg_id": "commit", "env": init_payload["commit"]},
            }
            commit_resp = await self._post_inbox(ready_initiator["session_token"], commit_frame)
            self.assertEqual(commit_resp.status, 200)
            commit_ack = await commit_resp.json()
            self.assertEqual(commit_ack["seq"], expected_seq)

            retry_resp = await self._post_inbox(ready_initiator["session_token"], commit_frame)
            self.assertEqual(retry_resp.status, 200)
            retry_ack = await retry_resp.json()
            self.assertEqual(retry_ack["seq"], expected_seq)

            evt_type_init_commit, commit_evt_init = await read_sse_event(initiator_sse)
            evt_type_join_commit, commit_evt_join = await read_sse_event(joiner_sse)
            self.assertEqual(evt_type_init_commit, "conv.event")
            self.assertEqual(evt_type_join_commit, "conv.event")
            self.assertEqual(commit_evt_init["body"]["seq"], expected_seq)
            self.assertEqual(commit_evt_join["body"]["seq"], expected_seq)
            await self._run_harness(
                env, "dm-commit-apply", "--state-dir", join_dir, "--commit", commit_evt_join["body"]["env"]
            )
            await self._run_harness(
                env, "dm-commit-apply", "--state-dir", init_dir, "--commit", commit_evt_init["body"]["env"]
            )

            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(read_sse_event(joiner_sse), timeout=0.2)

            expected_seq += 1

            def _clone_state(src: str, dest: Path):
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)

            async def send_and_receive(
                sender_env: dict,
                sender_dir: str,
                sender_sse,
                receiver_sse,
                receiver_dir: str,
                msg_id: str,
                plaintext: str,
            ) -> str:
                nonlocal expected_seq
                ct = await self._run_harness(env, "dm-encrypt", "--state-dir", sender_dir, "--plaintext", plaintext)
                frame = {
                    "v": 1,
                    "t": "conv.send",
                    "id": msg_id,
                    "body": {"conv_id": conv_id, "msg_id": msg_id, "env": ct},
                }
                resp = await self._post_inbox(sender_env["session_token"], frame)
                self.assertEqual(resp.status, 200)
                ack = await resp.json()
                self.assertEqual(ack["seq"], expected_seq)

                evt_type_sender, sender_evt = await read_sse_event(sender_sse)
                evt_type_receiver, receiver_evt = await read_sse_event(receiver_sse)
                self.assertEqual(evt_type_sender, "conv.event")
                self.assertEqual(evt_type_receiver, "conv.event")
                self.assertEqual(sender_evt["body"]["seq"], expected_seq)
                self.assertEqual(receiver_evt["body"]["seq"], expected_seq)
                self.assertEqual(receiver_evt["body"]["msg_id"], msg_id)

                decrypted = await self._run_harness(
                    env,
                    "dm-decrypt",
                    "--state-dir",
                    receiver_dir,
                    "--ciphertext",
                    receiver_evt["body"]["env"],
                )
                self.assertEqual(decrypted, plaintext)
                expected_seq += 1
                return receiver_evt["body"]["env"]

            initiator_env = {"session_token": ready_initiator["session_token"], "state_dir": init_dir}

            with tempfile.TemporaryDirectory() as join_clone_tmp:
                join_clone_dir = Path(join_clone_tmp) / "state"

                await send_and_receive(
                    initiator_env, init_dir, initiator_sse, joiner_sse, join_dir, "msg-1", "hi-joiner"
                )
                _clone_state(join_dir, join_clone_dir)

                joiner_stale_cipher = await send_and_receive(
                    initiator_env, init_dir, initiator_sse, joiner_sse, join_dir, "msg-2", "follow-up"
                )
                shutil.rmtree(join_clone_dir)
                join_clone_dir.mkdir(parents=True, exist_ok=True)
                rc, _, _ = await self._run_harness_raw(
                    env,
                    "dm-decrypt",
                    "--state-dir",
                    str(join_clone_dir),
                    "--ciphertext",
                    joiner_stale_cipher,
                )
                self.assertIsNotNone(rc)
                self.assertNotEqual(rc, 0)

                _clone_state(join_dir, join_clone_dir)
                joiner_resync_cipher = await send_and_receive(
                    initiator_env, init_dir, initiator_sse, joiner_sse, join_dir, "msg-2-resync", "resynced"
                )
                cloned_resync_plaintext = await self._run_harness(
                    env,
                    "dm-decrypt",
                    "--state-dir",
                    str(join_clone_dir),
                    "--ciphertext",
                    joiner_resync_cipher,
                )
                self.assertEqual(cloned_resync_plaintext, "resynced")

            await initiator_sse.release()
            await joiner_sse.release()

    async def test_room_bootstrap_add_and_app_roundtrip_over_ds(self):
        env: Dict[str, str] = dict(self.harness_env)

        owner_auth = "Bearer owner"
        peer_one_auth = "Bearer peer_one"
        peer_two_auth = "Bearer peer_two"
        peer_three_auth = "Bearer peer_three"
        conv_id = "room-conv-1"

        ready_owner = await self._start_session_http(auth_token=owner_auth, device_id="dev-owner")
        ready_peer_one = await self._start_session_http(auth_token=peer_one_auth, device_id="dev-peer-1")
        ready_peer_two = await self._start_session_http(auth_token=peer_two_auth, device_id="dev-peer-2")
        ready_peer_three = await self._start_session_http(auth_token=peer_three_auth, device_id="dev-peer-3")

        await self._create_room(ready_owner["session_token"], conv_id)
        await self._invite_member(ready_owner["session_token"], conv_id, ready_peer_one["user_id"])
        await self._invite_member(ready_owner["session_token"], conv_id, ready_peer_two["user_id"])

        async def open_sse(session_token: str):
            resp = await self.client.get(
                "/v1/sse",
                params={"conv_id": conv_id, "from_seq": "1"},
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(resp.status, 200)
            return resp

        async def read_events(sse_map: Dict[str, TestClient], expected_seq: int):
            events: Dict[str, dict] = {}
            for name, sse in sse_map.items():
                while True:
                    event_type, event = await read_sse_event(sse)
                    self.assertEqual(event_type, "conv.event")
                    event_seq = event["body"]["seq"]
                    if event_seq < expected_seq:
                        continue
                    self.assertEqual(event_seq, expected_seq)
                    events[name] = event
                    break
            return events

        with (
            tempfile.TemporaryDirectory(prefix="owner-") as owner_dir,
            tempfile.TemporaryDirectory(prefix="peer-one-") as peer_one_dir,
            tempfile.TemporaryDirectory(prefix="peer-two-") as peer_two_dir,
            tempfile.TemporaryDirectory(prefix="peer-three-") as peer_three_dir,
        ):
            owner_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", owner_dir, "--name", "owner", "--seed", "9101"
            )
            peer_one_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", peer_one_dir, "--name", "peer_one", "--seed", "9102"
            )
            peer_two_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", peer_two_dir, "--name", "peer_two", "--seed", "9103"
            )
            peer_three_kp = await self._run_harness(
                env, "dm-keypackage", "--state-dir", peer_three_dir, "--name", "peer_three", "--seed", "9104"
            )

            await self._publish_keypackages(ready_owner["session_token"], "dev-owner", [owner_kp])
            await self._publish_keypackages(ready_peer_one["session_token"], "dev-peer-1", [peer_one_kp])
            await self._publish_keypackages(ready_peer_two["session_token"], "dev-peer-2", [peer_two_kp])
            await self._publish_keypackages(ready_peer_three["session_token"], "dev-peer-3", [peer_three_kp])

            peer_one_fetch = await self._fetch_keypackages(ready_owner["session_token"], ready_peer_one["user_id"], 1)
            peer_two_fetch = await self._fetch_keypackages(ready_owner["session_token"], ready_peer_two["user_id"], 1)
            self.assertEqual(len(peer_one_fetch), 1)
            self.assertEqual(len(peer_two_fetch), 1)

            init_output = await self._run_harness(
                env,
                "group-init",
                "--state-dir",
                owner_dir,
                "--peer-keypackage",
                peer_one_fetch[0],
                "--peer-keypackage",
                peer_two_fetch[0],
                "--group-id",
                "cm9vbS1ncm91cA==",
                "--seed",
                "7001",
            )
            init_payload = json.loads(init_output)

            owner_sse = await open_sse(ready_owner["session_token"])
            peer_one_sse = await open_sse(ready_peer_one["session_token"])
            peer_two_sse = await open_sse(ready_peer_two["session_token"])

            expected_seq = 1
            welcome_env = pack_dm_env(1, init_payload["welcome"])
            welcome_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "room-welcome-1",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(welcome_env),
                    "env": welcome_env,
                },
            }
            welcome_resp = await self._post_inbox(ready_owner["session_token"], welcome_frame)
            self.assertEqual(welcome_resp.status, 200)
            welcome_ack = await welcome_resp.json()
            self.assertEqual(welcome_ack["seq"], expected_seq)

            welcome_events = await read_events(
                {"owner": owner_sse, "peer_one": peer_one_sse, "peer_two": peer_two_sse}, expected_seq
            )
            for event in welcome_events.values():
                self.assertEqual(event["body"]["seq"], expected_seq)
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            _, peer_one_welcome = unpack_dm_env(welcome_events["peer_one"]["body"]["env"])
            _, peer_two_welcome = unpack_dm_env(welcome_events["peer_two"]["body"]["env"])
            await self._run_harness(env, "dm-join", "--state-dir", peer_one_dir, "--welcome", peer_one_welcome)
            await self._run_harness(env, "dm-join", "--state-dir", peer_two_dir, "--welcome", peer_two_welcome)

            expected_seq += 1
            commit_env = pack_dm_env(2, init_payload["commit"])
            commit_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "room-commit-1",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(commit_env),
                    "env": commit_env,
                },
            }
            commit_resp = await self._post_inbox(ready_owner["session_token"], commit_frame)
            self.assertEqual(commit_resp.status, 200)
            commit_ack = await commit_resp.json()
            self.assertEqual(commit_ack["seq"], expected_seq)

            commit_events = await read_events(
                {"owner": owner_sse, "peer_one": peer_one_sse, "peer_two": peer_two_sse}, expected_seq
            )
            for event in commit_events.values():
                self.assertEqual(event["body"]["seq"], expected_seq)
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("owner", owner_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                _, commit_payload = unpack_dm_env(commit_events[member]["body"]["env"])
                await self._run_harness(
                    env, "dm-commit-apply", "--state-dir", state_dir, "--commit", commit_payload
                )

            expected_seq += 1
            first_plaintext = "room-app-1"
            first_cipher = await self._run_harness(
                env, "dm-encrypt", "--state-dir", owner_dir, "--plaintext", first_plaintext
            )
            first_env = pack_dm_env(3, first_cipher)
            first_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "room-app-1",
                "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(first_env), "env": first_env},
            }
            first_resp = await self._post_inbox(ready_owner["session_token"], first_frame)
            self.assertEqual(first_resp.status, 200)
            first_ack = await first_resp.json()
            self.assertEqual(first_ack["seq"], expected_seq)

            first_events = await read_events(
                {"owner": owner_sse, "peer_one": peer_one_sse, "peer_two": peer_two_sse}, expected_seq
            )
            for member, state_dir in (
                ("owner", owner_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                event = first_events[member]
                self.assertEqual(event["body"]["seq"], expected_seq)
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                _, app_payload = unpack_dm_env(first_events[member]["body"]["env"])
                decrypted = await self._run_harness(
                    env, "dm-decrypt", "--state-dir", state_dir, "--ciphertext", app_payload
                )
                self.assertEqual(decrypted, first_plaintext)

            expected_seq += 1
            await self._invite_member(ready_owner["session_token"], conv_id, ready_peer_three["user_id"])
            peer_three_fetch = await self._fetch_keypackages(
                ready_owner["session_token"], ready_peer_three["user_id"], 1
            )
            self.assertEqual(len(peer_three_fetch), 1)

            add_output = await self._run_harness(
                env,
                "group-add",
                "--state-dir",
                owner_dir,
                "--peer-keypackage",
                peer_three_fetch[0],
                "--seed",
                "7002",
            )
            add_payload = json.loads(add_output)
            add_proposals = add_payload["proposals"]
            self.assertEqual(len(add_proposals), 1)

            peer_three_sse = await open_sse(ready_peer_three["session_token"])

            add_proposal_env = pack_dm_env(2, add_proposals[0])
            add_proposal_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "room-add-proposal-1",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(add_proposal_env),
                    "env": add_proposal_env,
                },
            }
            add_proposal_resp = await self._post_inbox(ready_owner["session_token"], add_proposal_frame)
            self.assertEqual(add_proposal_resp.status, 200)
            add_proposal_ack = await add_proposal_resp.json()
            self.assertEqual(add_proposal_ack["seq"], expected_seq)

            add_proposal_events = await read_events(
                {
                    "owner": owner_sse,
                    "peer_one": peer_one_sse,
                    "peer_two": peer_two_sse,
                    "peer_three": peer_three_sse,
                },
                expected_seq,
            )
            for event in add_proposal_events.values():
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                _, proposal_payload = unpack_dm_env(add_proposal_events[member]["body"]["env"])
                await self._run_harness(
                    env, "dm-commit-apply", "--state-dir", state_dir, "--commit", proposal_payload
                )

            expected_seq += 1
            add_welcome_env = pack_dm_env(1, add_payload["welcome"])
            add_welcome_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "room-welcome-2",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(add_welcome_env),
                    "env": add_welcome_env,
                },
            }
            add_welcome_resp = await self._post_inbox(ready_owner["session_token"], add_welcome_frame)
            self.assertEqual(add_welcome_resp.status, 200)
            add_welcome_ack = await add_welcome_resp.json()
            self.assertEqual(add_welcome_ack["seq"], expected_seq)

            add_welcome_events = await read_events(
                {
                    "owner": owner_sse,
                    "peer_one": peer_one_sse,
                    "peer_two": peer_two_sse,
                    "peer_three": peer_three_sse,
                },
                expected_seq,
            )
            for event in add_welcome_events.values():
                self.assertEqual(event["body"]["seq"], expected_seq)
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            _, peer_three_welcome = unpack_dm_env(add_welcome_events["peer_three"]["body"]["env"])
            await self._run_harness(
                env, "dm-join", "--state-dir", peer_three_dir, "--welcome", peer_three_welcome
            )

            expected_seq += 1
            add_commit_env = pack_dm_env(2, add_payload["commit"])
            add_commit_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "room-commit-2",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id_for_env(add_commit_env),
                    "env": add_commit_env,
                },
            }
            add_commit_resp = await self._post_inbox(ready_owner["session_token"], add_commit_frame)
            self.assertEqual(add_commit_resp.status, 200)
            add_commit_ack = await add_commit_resp.json()
            self.assertEqual(add_commit_ack["seq"], expected_seq)

            add_commit_events = await read_events(
                {
                    "owner": owner_sse,
                    "peer_one": peer_one_sse,
                    "peer_two": peer_two_sse,
                    "peer_three": peer_three_sse,
                },
                expected_seq,
            )
            for event in add_commit_events.values():
                self.assertEqual(event["body"]["seq"], expected_seq)
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("owner", owner_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
            ):
                _, commit_payload = unpack_dm_env(add_commit_events[member]["body"]["env"])
                await self._run_harness(
                    env, "dm-commit-apply", "--state-dir", state_dir, "--commit", commit_payload
                )

            expected_seq += 1
            second_plaintext = "room-app-2"
            second_cipher = await self._run_harness(
                env, "dm-encrypt", "--state-dir", peer_one_dir, "--plaintext", second_plaintext
            )
            second_env = pack_dm_env(3, second_cipher)
            second_frame = {
                "v": 1,
                "t": "conv.send",
                "id": "room-app-2",
                "body": {"conv_id": conv_id, "msg_id": msg_id_for_env(second_env), "env": second_env},
            }
            second_resp = await self._post_inbox(ready_peer_one["session_token"], second_frame)
            self.assertEqual(second_resp.status, 200)
            second_ack = await second_resp.json()
            self.assertEqual(second_ack["seq"], expected_seq)

            second_events = await read_events(
                {
                    "owner": owner_sse,
                    "peer_one": peer_one_sse,
                    "peer_two": peer_two_sse,
                    "peer_three": peer_three_sse,
                },
                expected_seq,
            )
            for member, state_dir in (
                ("owner", owner_dir),
                ("peer_one", peer_one_dir),
                ("peer_two", peer_two_dir),
                ("peer_three", peer_three_dir),
            ):
                event = second_events[member]
                self.assertEqual(event["body"]["seq"], expected_seq)
                self.assertEqual(event["body"]["msg_id"], msg_id_for_env(event["body"]["env"]))

            for member, state_dir in (
                ("owner", owner_dir),
                ("peer_two", peer_two_dir),
                ("peer_three", peer_three_dir),
            ):
                _, app_payload = unpack_dm_env(second_events[member]["body"]["env"])
                decrypted = await self._run_harness(
                    env, "dm-decrypt", "--state-dir", state_dir, "--ciphertext", app_payload
                )
                self.assertEqual(decrypted, second_plaintext)

            await owner_sse.release()
            await peer_one_sse.release()
            await peer_two_sse.release()
            await peer_three_sse.release()
