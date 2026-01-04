import asyncio
import importlib
import importlib.metadata
import json
import os
import re
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


class MlsDmOverDsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(ping_interval_s=3600)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    def _parse_go_version(self, raw: str) -> Optional[Tuple[int, int, int]]:
        match = re.search(r"go(\d+)\.(\d+)(?:\.(\d+))?", raw)
        if not match:
            return None

        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch or 0)

    def _get_go_version(self, go_bin: str) -> Optional[Tuple[int, int, int]]:
        for args in ([go_bin, "env", "GOVERSION"], [go_bin, "version"]):
            try:
                output = subprocess.check_output(args, text=True).strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

            parsed = self._parse_go_version(output)
            if parsed:
                return parsed

        return None

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

    async def _run_harness(self, env: Dict[str, str], *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            str(self.harness_bin),
            *args,
            cwd=self.harness_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.harness_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            self.fail(f"mls-harness {' '.join(args)} timed out after {self.harness_timeout} seconds")

        if proc.returncode != 0:
            self.fail(
                f"mls-harness {' '.join(args)} failed with code {proc.returncode}\n"
                f"stdout:\n{stdout.decode()}\n"
                f"stderr:\n{stderr.decode()}\n"
            )
        return stdout.decode().strip()

    async def test_dm_roundtrip_over_ds(self):
        go_bin = shutil.which("go")
        if not go_bin:
            self.skipTest("Go toolchain not available")

        go_version = self._get_go_version(go_bin)
        if not go_version:
            self.skipTest("Unable to determine Go version")
        if go_version < (1, 22, 0):
            self.skipTest("Go >= 1.22 required for MLS harness DM test")

        env: Dict[str, str] = dict(os.environ)
        env.setdefault("GOTOOLCHAIN", "local")
        env.setdefault("GOFLAGS", "-mod=vendor")
        env.setdefault("GOMAXPROCS", "1")
        env.setdefault("GOMEMLIMIT", "700MiB")

        self.harness_dir = Path(__file__).resolve().parents[2] / "tools" / "mls_harness"
        with tempfile.TemporaryDirectory() as harness_tmpdir:
            self.harness_bin = Path(harness_tmpdir) / "mls-harness"
            build = subprocess.run(
                [
                    go_bin,
                    "build",
                    "-mod=vendor",
                    "-p",
                    "1",
                    "-o",
                    str(self.harness_bin),
                    "./cmd/mls-harness",
                ],
                cwd=self.harness_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=180,
            )
            if build.returncode != 0:
                self.fail(
                    "mls-harness build failed\n"
                    f"stdout:\n{build.stdout}\n"
                    f"stderr:\n{build.stderr}\n"
                )

            self.harness_timeout = 10

            initiator_auth = "Bearer initiator"
            joiner_auth = "Bearer joiner"
            conv_id = "dm-conv-1"

            ready_initiator = await self._start_session_http(auth_token=initiator_auth, device_id="dev-init")
            ready_joiner = await self._start_session_http(auth_token=joiner_auth, device_id="dev-join")

            await self._create_room(ready_initiator["session_token"], conv_id)
            await self._invite_member(ready_initiator["session_token"], conv_id, ready_joiner["user_id"])

            with tempfile.TemporaryDirectory() as init_dir, tempfile.TemporaryDirectory() as join_dir:
                initiator_kp = await self._run_harness(env, "dm-keypackage", "--state-dir", init_dir, "--name", "initiator", "--seed", "9001")
                joiner_kp = await self._run_harness(env, "dm-keypackage", "--state-dir", join_dir, "--name", "joiner", "--seed", "9002")

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
                await self._run_harness(env, "dm-join", "--state-dir", join_dir, "--welcome", welcome_evt_join["body"]["env"])

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
                await self._run_harness(env, "dm-commit-apply", "--state-dir", join_dir, "--commit", commit_evt_join["body"]["env"])
                await self._run_harness(env, "dm-commit-apply", "--state-dir", init_dir, "--commit", commit_evt_init["body"]["env"])

                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(read_sse_event(joiner_sse), timeout=0.25)

                expected_seq += 1
                retry_plaintext = "hello-once"
                retry_cipher = await self._run_harness(env, "dm-encrypt", "--state-dir", init_dir, "--plaintext", retry_plaintext)
                retry_frame = {
                    "v": 1,
                    "t": "conv.send",
                    "id": "app-retry",
                    "body": {"conv_id": conv_id, "msg_id": "app-retry", "env": retry_cipher},
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
                self.assertEqual(retry_evt_init["body"]["msg_id"], "app-retry")
                self.assertEqual(retry_evt_join["body"]["msg_id"], "app-retry")
                decrypted_retry = await self._run_harness(
                    env,
                    "dm-decrypt",
                    "--state-dir",
                    join_dir,
                    "--ciphertext",
                    retry_evt_join["body"]["env"],
                )
                self.assertEqual(decrypted_retry, retry_plaintext)

                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(read_sse_event(joiner_sse), timeout=0.25)

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

                initiator_env = {"session_token": ready_initiator["session_token"], "state_dir": init_dir}
                joiner_env = {"session_token": ready_joiner["session_token"], "state_dir": join_dir}

                await send_and_confirm(initiator_env, init_dir, initiator_sse, joiner_sse, join_dir, "msg-1", "hi-joiner")
                await send_and_confirm(joiner_env, join_dir, joiner_sse, initiator_sse, init_dir, "msg-2", "hi-initiator")
                await send_and_confirm(initiator_env, init_dir, initiator_sse, joiner_sse, join_dir, "msg-3", "follow-up")
                await send_and_confirm(joiner_env, join_dir, joiner_sse, initiator_sse, init_dir, "msg-4", "ack")

                await initiator_sse.release()
                await joiner_sse.release()
