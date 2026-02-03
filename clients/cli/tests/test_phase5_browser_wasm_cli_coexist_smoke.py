import asyncio
import base64
import contextlib
import functools
import hashlib
import http.server
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY_SRC = ROOT_DIR / "gateway" / "src"
GATEWAY_TESTS = ROOT_DIR / "gateway" / "tests"
WASM_MODULE_DIR = ROOT_DIR / "tools" / "mls_harness"
WASM_EXEC_SRC = ROOT_DIR / "clients" / "web" / "vendor" / "wasm_exec.js"

import sys

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


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_wasm(output_path: Path) -> None:
    go_bin = shutil.which("go")
    if not go_bin:
        raise unittest.SkipTest("Go toolchain not available")
    env = os.environ.copy()
    env["GOOS"] = "js"
    env["GOARCH"] = "wasm"
    env["GOFLAGS"] = "-mod=vendor -trimpath -buildvcs=false"
    env["GOTOOLCHAIN"] = "local"
    subprocess.run(
        [go_bin, "-C", str(WASM_MODULE_DIR), "build", "-o", str(output_path), "./cmd/mls-wasm"],
        cwd=ROOT_DIR,
        env=env,
        check=True,
    )


def _start_static_server(root: Path) -> tuple[http.server.ThreadingHTTPServer, threading.Thread]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _wait_for_cdp_url(port: int, timeout_s: float = 5.0) -> str:
    deadline = time.time() + timeout_s
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                ws_url = payload.get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url
        except Exception as exc:  # noqa: BLE001 - error details not needed here
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for Chromium DevTools URL: {last_error}")


def _terminate_process(proc: Optional[subprocess.Popen[str]], label: str, timeout_s: float = 5.0) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout_s)


def _format_cdp_state(ws_url: str) -> str:
    parsed = urllib.parse.urlparse(ws_url)
    if not parsed.hostname or not parsed.port:
        return "unavailable"
    url = f"http://{parsed.hostname}:{parsed.port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        return f"error: {exc}"
    return json.dumps(payload, sort_keys=True)


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


async def _ws_recv_until(ws, *, timeout_s: float, predicate: Callable[[dict], bool]) -> dict:
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


async def _cdp_wait_for_sentinel(ws_url: str, page_url: str, timeout_s: float) -> None:
    console_lines: list[str] = []
    async with ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            await ws.send_json({"id": 1, "method": "Runtime.enable"})
            await ws.send_json({"id": 2, "method": "Page.enable"})
            await ws.send_json({"id": 3, "method": "Page.navigate", "params": {"url": page_url}})

            deadline = asyncio.get_running_loop().time() + timeout_s
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    cdp_state = await asyncio.to_thread(_format_cdp_state, ws_url)
                    console_tail = console_lines[-5:]
                    raise AssertionError(
                        "Timed out waiting for browser sentinel; "
                        f"cdp_ws_url={ws_url}; cdp_state={cdp_state}; console_tail={console_tail}"
                    )
                msg = await ws.receive(timeout=remaining)
                if msg.type == WSMsgType.TEXT:
                    payload = json.loads(msg.data)
                else:
                    continue
                if payload.get("method") != "Runtime.consoleAPICalled":
                    continue
                params = payload.get("params")
                if not isinstance(params, dict):
                    continue
                args = params.get("args")
                if not isinstance(args, list):
                    continue
                console_text = None
                for arg in args:
                    if not isinstance(arg, dict):
                        continue
                    value = arg.get("value")
                    if not isinstance(value, str):
                        continue
                    console_text = value
                    if value.startswith("PHASE5_BROWSER_SMOKE_PASS"):
                        return
                    if value.startswith("PHASE5_BROWSER_SMOKE_FAIL"):
                        raise AssertionError(value)
                if console_text:
                    console_lines.append(console_text)
                    if len(console_lines) > 20:
                        console_lines = console_lines[-20:]


class Phase5BrowserWasmCliCoexistSmokeTests(unittest.IsolatedAsyncioTestCase):
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

    async def _publish_keypackages(self, session_token: str, device_id: str, keypackages: list[str]) -> None:
        resp = await self.client.post(
            "/v1/keypackages",
            json={"device_id": device_id, "keypackages": keypackages},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _bob_flow(
        self,
        *,
        ws,
        conv_ids: dict[str, str],
        bob_dm_dir: Path,
        bob_room_dir: Path,
    ) -> None:
        expected_seq = {"dm": 1, "room": 1}

        dm_welcome_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["dm"],
            expected_seq=expected_seq["dm"],
            timeout_s=2.0,
        )
        dm_welcome_kind, dm_welcome_payload = dm_envelope.unpack(dm_welcome_event["body"]["env"])
        self.assertEqual(dm_welcome_kind, 1)
        await self._run_harness(
            "dm-join",
            "--state-dir",
            str(bob_dm_dir),
            "--welcome",
            dm_welcome_payload,
        )

        room_welcome_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["room"],
            expected_seq=expected_seq["room"],
            timeout_s=2.0,
        )
        room_welcome_kind, room_welcome_payload = dm_envelope.unpack(room_welcome_event["body"]["env"])
        self.assertEqual(room_welcome_kind, 1)
        await self._run_harness(
            "dm-join",
            "--state-dir",
            str(bob_room_dir),
            "--welcome",
            room_welcome_payload,
        )

        expected_seq["dm"] += 1
        dm_commit_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["dm"],
            expected_seq=expected_seq["dm"],
            timeout_s=2.0,
        )
        dm_commit_kind, dm_commit_payload = dm_envelope.unpack(dm_commit_event["body"]["env"])
        self.assertEqual(dm_commit_kind, 2)
        await self._run_harness(
            "dm-commit-apply",
            "--state-dir",
            str(bob_dm_dir),
            "--commit",
            dm_commit_payload,
        )

        expected_seq["room"] += 1
        room_commit_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["room"],
            expected_seq=expected_seq["room"],
            timeout_s=2.0,
        )
        room_commit_kind, room_commit_payload = dm_envelope.unpack(room_commit_event["body"]["env"])
        self.assertEqual(room_commit_kind, 2)
        await self._run_harness(
            "dm-commit-apply",
            "--state-dir",
            str(bob_room_dir),
            "--commit",
            room_commit_payload,
        )

        expected_seq["dm"] += 1
        dm_app_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["dm"],
            expected_seq=expected_seq["dm"],
            timeout_s=2.0,
        )
        dm_app_kind, dm_app_payload = dm_envelope.unpack(dm_app_event["body"]["env"])
        self.assertEqual(dm_app_kind, 3)
        dm_plaintext = await self._run_harness(
            "dm-decrypt",
            "--state-dir",
            str(bob_dm_dir),
            "--ciphertext",
            dm_app_payload,
        )
        self.assertEqual(dm_plaintext, "dm:hello-from-browser")
        dm_reply_cipher = await self._run_harness(
            "dm-encrypt",
            "--state-dir",
            str(bob_dm_dir),
            "--plaintext",
            "dm:reply-from-bob",
        )
        dm_reply_env = dm_envelope.pack(3, dm_reply_cipher)
        await ws.send_json(
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
        dm_reply_seq = await _ws_wait_for_ack(ws, request_id="dm-app-bob", timeout_s=2.0)
        self.assertEqual(dm_reply_seq, expected_seq["dm"] + 1)
        expected_seq["dm"] += 1
        await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["dm"],
            expected_seq=expected_seq["dm"],
            timeout_s=2.0,
        )

        await _ws_assert_no_conv_event(ws, conv_id=conv_ids["dm"], timeout_s=0.4)

        expected_seq["room"] += 1
        room_app_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["room"],
            expected_seq=expected_seq["room"],
            timeout_s=2.0,
        )
        room_app_kind, room_app_payload = dm_envelope.unpack(room_app_event["body"]["env"])
        self.assertEqual(room_app_kind, 3)
        room_plaintext = await self._run_harness(
            "dm-decrypt",
            "--state-dir",
            str(bob_room_dir),
            "--ciphertext",
            room_app_payload,
        )
        self.assertEqual(room_plaintext, "room:hello-from-browser")
        room_reply_cipher = await self._run_harness(
            "dm-encrypt",
            "--state-dir",
            str(bob_room_dir),
            "--plaintext",
            "room:reply-from-bob",
        )
        room_reply_env = dm_envelope.pack(3, room_reply_cipher)
        await ws.send_json(
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
        room_reply_seq = await _ws_wait_for_ack(ws, request_id="room-app-bob", timeout_s=2.0)
        self.assertEqual(room_reply_seq, expected_seq["room"] + 1)
        expected_seq["room"] += 1
        await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["room"],
            expected_seq=expected_seq["room"],
            timeout_s=2.0,
        )

    async def test_browser_wasm_cli_coexist_smoke(self) -> None:
        chromium_bin = shutil.which("chromium")
        if not chromium_bin:
            raise unittest.SkipTest("chromium not available in PATH")

        conv_ids = {"dm": "conv_dm_browser", "room": "conv_room_browser"}
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

        bob_ws = await _ws_open_session(self.client, "dev-bob", bob_auth)
        for conv_id in conv_ids.values():
            await _ws_subscribe(bob_ws, conv_id=conv_id, from_seq=1)

        chromium_proc: Optional[subprocess.Popen[str]] = None
        static_server: Optional[http.server.ThreadingHTTPServer] = None
        static_thread: Optional[threading.Thread] = None

        try:
            with (
                tempfile.TemporaryDirectory(prefix="bob-dm-") as bob_dm_dir,
                tempfile.TemporaryDirectory(prefix="bob-room-") as bob_room_dir,
                tempfile.TemporaryDirectory(prefix="wasm-build-") as wasm_dir,
                tempfile.TemporaryDirectory(prefix="browser-static-") as static_dir,
                tempfile.TemporaryDirectory(prefix="chromium-user-") as chrome_profile,
            ):
                bob_dm_dir = Path(bob_dm_dir)
                bob_room_dir = Path(bob_room_dir)
                wasm_dir = Path(wasm_dir)
                static_dir = Path(static_dir)
                chrome_profile = Path(chrome_profile)

                bob_dm_kp = await self._run_harness(
                    "dm-keypackage",
                    "--state-dir",
                    str(bob_dm_dir),
                    "--name",
                    "bob-dm",
                    "--seed",
                    "44001",
                )
                bob_room_kp = await self._run_harness(
                    "dm-keypackage",
                    "--state-dir",
                    str(bob_room_dir),
                    "--name",
                    "bob-room",
                    "--seed",
                    "44002",
                )

                await self._publish_keypackages(bob_ready["session_token"], "dev-bob", [bob_dm_kp, bob_room_kp])

                wasm_output = wasm_dir / "mls_harness.wasm"
                _build_wasm(wasm_output)

                shutil.copy(WASM_EXEC_SRC, static_dir / "wasm_exec.js")
                shutil.copy(wasm_output, static_dir / "mls_harness.wasm")

                smoke_js = static_dir / "smoke.js"
                smoke_js.write_text(
                    """
(async () => {
  const report = (msg) => console.log(msg);
  const params = new URLSearchParams(window.location.search);
  const payload_b64 = params.get('payload');
  if (!payload_b64) {
    report('PHASE5_BROWSER_SMOKE_FAIL: missing payload');
    return;
  }
  const payload = JSON.parse(atob(payload_b64));
  const gateway_url = payload.gateway_url;
  const ws_url = gateway_url.replace('http://', 'ws://').replace('https://', 'wss://') + '/v1/ws';

  const bytesToBase64 = (bytes) => {
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  };
  const base64ToBytes = (b64) => {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  };
  const packEnv = (kind, payload_b64) => {
    const payload_bytes = base64ToBytes(payload_b64);
    const env_bytes = new Uint8Array(1 + payload_bytes.length);
    env_bytes[0] = kind;
    env_bytes.set(payload_bytes, 1);
    return bytesToBase64(env_bytes);
  };
  const unpackEnv = (env_b64) => {
    const env_bytes = base64ToBytes(env_b64);
    if (env_bytes.length === 0) {
      throw new Error('env missing kind');
    }
    const kind = env_bytes[0];
    const payload_b64 = bytesToBase64(env_bytes.slice(1));
    return { kind, payload_b64 };
  };

  const go = new Go();
  const wasm_resp = await fetch('mls_harness.wasm');
  const wasm_bytes = await wasm_resp.arrayBuffer();
  const wasm_inst = await WebAssembly.instantiate(wasm_bytes, go.importObject);
  go.run(wasm_inst.instance);

  const ensureOk = (result, label) => {
    if (!result || !result.ok) {
      const err = result && result.error ? result.error : 'unknown error';
      throw new Error(label + ': ' + err);
    }
    return result;
  };

  const ws = new WebSocket(ws_url);
  const queue = [];
  const waiters = [];
  const dispatch = (payload) => {
    for (let i = 0; i < waiters.length; i += 1) {
      const waiter = waiters[i];
      if (waiter.predicate(payload)) {
        waiters.splice(i, 1);
        waiter.resolve(payload);
        return;
      }
    }
    queue.push(payload);
  };
  const waitFor = (predicate, timeout_ms) => new Promise((resolve, reject) => {
    for (let i = 0; i < queue.length; i += 1) {
      if (predicate(queue[i])) {
        resolve(queue.splice(i, 1)[0]);
        return;
      }
    }
    const timeout = setTimeout(() => {
      const idx = waiters.findIndex((w) => w.resolve === resolve);
      if (idx !== -1) {
        waiters.splice(idx, 1);
      }
      reject(new Error('timeout waiting for ws message'));
    }, timeout_ms);
    waiters.push({
      predicate,
      resolve: (payload) => {
        clearTimeout(timeout);
        resolve(payload);
      },
    });
  });

  ws.onmessage = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    if (payload && payload.t === 'ping') {
      ws.send(JSON.stringify({ v: 1, t: 'pong', id: payload.id }));
      return;
    }
    dispatch(payload);
  };
  await new Promise((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error('ws error'));
  });

  const send = async (body) => {
    ws.send(JSON.stringify(body));
  };

  const sendWithAck = async (body) => {
    await send(body);
    const ack = await waitFor(
      (payload) => payload.t === 'conv.acked' && payload.id === body.id,
      2000,
    );
    return ack.body.seq;
  };

  const expectEvent = async (conv_id, seq) => {
    const event = await waitFor(
      (payload) => payload.t === 'conv.event'
        && payload.body
        && payload.body.conv_id === conv_id
        && payload.body.seq === seq,
      2000,
    );
    return event;
  };

  try {
    await send({
      v: 1,
      t: 'session.start',
      id: 'session-start',
      body: { auth_token: payload.alice_auth, device_id: payload.alice_device },
    });
    await waitFor((msg) => msg.t === 'session.ready', 2000);

    await send({ v: 1, t: 'conv.subscribe', id: 'sub-dm', body: { conv_id: payload.conv_ids.dm, from_seq: 1 } });
    await send({ v: 1, t: 'conv.subscribe', id: 'sub-room', body: { conv_id: payload.conv_ids.room, from_seq: 1 } });

    const alice_dm_create = ensureOk(globalThis.dmCreateParticipant('alice-dm', payload.seed_dm));
    const alice_room_create = ensureOk(globalThis.dmCreateParticipant('alice-room', payload.seed_room));
    const guest_create = ensureOk(globalThis.dmCreateParticipant('room-guest', payload.seed_guest));

    let alice_dm_participant = alice_dm_create.participant_b64;
    let alice_room_participant = alice_room_create.participant_b64;

    const dm_init = ensureOk(
      globalThis.dmInit(alice_dm_participant, payload.bob_keypackages.dm, payload.group_ids.dm, payload.seed_dm_init),
    );
    alice_dm_participant = dm_init.participant_b64;

    const dm_welcome_env = packEnv(1, dm_init.welcome_b64);
    const dm_commit_env = packEnv(2, dm_init.commit_b64);

    const dm_welcome_msg_id = payload.msg_ids.dm_welcome;
    const dm_welcome_seq = await sendWithAck({
      v: 1,
      t: 'conv.send',
      id: 'dm-welcome',
      body: { conv_id: payload.conv_ids.dm, msg_id: dm_welcome_msg_id, env: dm_welcome_env },
    });
    await expectEvent(payload.conv_ids.dm, dm_welcome_seq);

    const room_init = ensureOk(
      globalThis.groupInit(
        alice_room_participant,
        [payload.bob_keypackages.room, guest_create.keypackage_b64],
        payload.group_ids.room,
        payload.seed_room_init,
      ),
    );
    alice_room_participant = room_init.participant_b64;

    const room_welcome_env = packEnv(1, room_init.welcome_b64);
    const room_commit_env = packEnv(2, room_init.commit_b64);

    const room_welcome_seq = await sendWithAck({
      v: 1,
      t: 'conv.send',
      id: 'room-welcome',
      body: { conv_id: payload.conv_ids.room, msg_id: payload.msg_ids.room_welcome, env: room_welcome_env },
    });
    await expectEvent(payload.conv_ids.room, room_welcome_seq);

    const dm_commit_seq = await sendWithAck({
      v: 1,
      t: 'conv.send',
      id: 'dm-commit',
      body: { conv_id: payload.conv_ids.dm, msg_id: payload.msg_ids.dm_commit, env: dm_commit_env },
    });
    const dm_commit_event = await expectEvent(payload.conv_ids.dm, dm_commit_seq);
    const dm_commit_env_payload = unpackEnv(dm_commit_event.body.env).payload_b64;
    alice_dm_participant = ensureOk(
      globalThis.dmCommitApply(alice_dm_participant, dm_commit_env_payload),
      'dm commit apply',
    ).participant_b64;

    const room_commit_seq = await sendWithAck({
      v: 1,
      t: 'conv.send',
      id: 'room-commit',
      body: { conv_id: payload.conv_ids.room, msg_id: payload.msg_ids.room_commit, env: room_commit_env },
    });
    const room_commit_event = await expectEvent(payload.conv_ids.room, room_commit_seq);
    const room_commit_env_payload = unpackEnv(room_commit_event.body.env).payload_b64;
    alice_room_participant = ensureOk(
      globalThis.dmCommitApply(alice_room_participant, room_commit_env_payload),
      'room commit apply',
    ).participant_b64;

    const dm_cipher = ensureOk(globalThis.dmEncrypt(alice_dm_participant, payload.plaintext.dm_send)).ciphertext_b64;
    const dm_env = packEnv(3, dm_cipher);
    const dm_seq = await sendWithAck({
      v: 1,
      t: 'conv.send',
      id: 'dm-app',
      body: { conv_id: payload.conv_ids.dm, msg_id: payload.msg_ids.dm_app, env: dm_env },
    });
    await expectEvent(payload.conv_ids.dm, dm_seq);

    const dm_reply_event = await expectEvent(payload.conv_ids.dm, dm_seq + 1);
    const dm_reply_payload = unpackEnv(dm_reply_event.body.env).payload_b64;
    const dm_reply_plain = ensureOk(
      globalThis.dmDecrypt(alice_dm_participant, dm_reply_payload),
      'dm decrypt',
    ).plaintext;
    if (dm_reply_plain !== payload.plaintext.dm_reply) {
      throw new Error('unexpected dm reply');
    }

    const resend_seq = await sendWithAck({
      v: 1,
      t: 'conv.send',
      id: 'dm-app-retry',
      body: { conv_id: payload.conv_ids.dm, msg_id: payload.msg_ids.dm_app, env: dm_env },
    });
    if (resend_seq !== dm_seq) {
      throw new Error('dm resend returned different seq');
    }

    await new Promise((resolve) => setTimeout(resolve, 500));

    const room_cipher = ensureOk(globalThis.dmEncrypt(alice_room_participant, payload.plaintext.room_send)).ciphertext_b64;
    const room_env = packEnv(3, room_cipher);
    const room_seq = await sendWithAck({
      v: 1,
      t: 'conv.send',
      id: 'room-app',
      body: { conv_id: payload.conv_ids.room, msg_id: payload.msg_ids.room_app, env: room_env },
    });
    await expectEvent(payload.conv_ids.room, room_seq);

    const room_reply_event = await expectEvent(payload.conv_ids.room, room_seq + 1);
    const room_reply_payload = unpackEnv(room_reply_event.body.env).payload_b64;
    const room_reply_plain = ensureOk(
      globalThis.dmDecrypt(alice_room_participant, room_reply_payload),
      'room decrypt',
    ).plaintext;
    if (room_reply_plain !== payload.plaintext.room_reply) {
      throw new Error('unexpected room reply');
    }

    report('PHASE5_BROWSER_SMOKE_PASS');
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    report('PHASE5_BROWSER_SMOKE_FAIL: ' + msg);
  }
})();
""",
                    encoding="utf-8",
                )

                index_html = static_dir / "index.html"
                index_html.write_text(
                    """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Phase 5 browser wasm smoke</title>
    <script src="wasm_exec.js"></script>
    <script src="smoke.js"></script>
  </head>
  <body>
    <p>Phase 5 browser wasm smoke</p>
  </body>
</html>
""",
                    encoding="utf-8",
                )

                static_server, static_thread = _start_static_server(static_dir)

                payload = {
                    "gateway_url": self.base_url.rstrip("/"),
                    "alice_auth": alice_auth,
                    "alice_device": "dev-alice",
                    "conv_ids": conv_ids,
                    "group_ids": group_ids,
                    "bob_keypackages": {"dm": bob_dm_kp, "room": bob_room_kp},
                    "seed_dm": 51001,
                    "seed_room": 51002,
                    "seed_guest": 51003,
                    "seed_dm_init": 52001,
                    "seed_room_init": 52002,
                    "plaintext": {
                        "dm_send": "dm:hello-from-browser",
                        "dm_reply": "dm:reply-from-bob",
                        "room_send": "room:hello-from-browser",
                        "room_reply": "room:reply-from-bob",
                    },
                    "msg_ids": {
                        "dm_welcome": "dm-welcome",
                        "room_welcome": "room-welcome",
                        "dm_commit": "dm-commit",
                        "room_commit": "room-commit",
                        "dm_app": "dm-app",
                        "room_app": "room-app",
                    },
                }

                payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
                query = urllib.parse.urlencode({"payload": payload_b64})
                page_url = f"http://127.0.0.1:{static_server.server_port}/index.html?{query}"

                cdp_port = _find_free_port()
                chromium_proc = subprocess.Popen(
                    [
                        chromium_bin,
                        "--headless",
                        "--disable-gpu",
                        f"--remote-debugging-port={cdp_port}",
                        f"--user-data-dir={chrome_profile}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                try:
                    cdp_ws_url = _wait_for_cdp_url(cdp_port, timeout_s=5.0)
                except AssertionError as exc:
                    raise unittest.SkipTest(f"chromium remote debugging unavailable: {exc}") from exc

                bob_task = asyncio.create_task(
                    self._bob_flow(
                        ws=bob_ws,
                        conv_ids=conv_ids,
                        bob_dm_dir=bob_dm_dir,
                        bob_room_dir=bob_room_dir,
                    )
                )
                try:
                    await _cdp_wait_for_sentinel(cdp_ws_url, page_url, timeout_s=15.0)
                    await bob_task
                except Exception:
                    bob_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await bob_task
                    raise

        finally:
            await bob_ws.close()
            if static_server is not None:
                static_server.shutdown()
                static_server.server_close()
            if static_thread is not None:
                static_thread.join(timeout=2.0)
            _terminate_process(chromium_proc, "chromium")


if __name__ == "__main__":
    unittest.main()
