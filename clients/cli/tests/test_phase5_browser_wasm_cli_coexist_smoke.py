import asyncio
import base64
import contextlib
import functools
import hashlib
import http.server
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Optional

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY_SRC = ROOT_DIR / "gateway" / "src"
GATEWAY_TESTS = ROOT_DIR / "gateway" / "tests"
WASM_MODULE_DIR = ROOT_DIR / "tools" / "mls_harness"
WASM_EXEC_SRC = ROOT_DIR / "clients" / "web" / "vendor" / "wasm_exec.js"
WASM_PATH = ROOT_DIR / "clients" / "web" / "vendor" / "mls_harness.wasm"
WS_EVENT_TIMEOUT_S = 10.0
WS_ACK_TIMEOUT_S = 12.0
WS_READY_TIMEOUT_S = 4.0
WS_NO_EVENT_TIMEOUT_S = 1.0

import sys

if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))
if str(GATEWAY_TESTS) not in sys.path:
    sys.path.insert(0, str(GATEWAY_TESTS))
HELPERS_DIR = Path(__file__).resolve().parent / "helpers"
if str(HELPERS_DIR) not in sys.path:
    sys.path.insert(0, str(HELPERS_DIR))

from cli_app import dm_envelope
from gateway.ws_transport import create_app
from mls_harness_util import HARNESS_DIR, ensure_harness_binary, make_harness_env, run_harness
from chromium_cdp import find_chromium, find_free_port, start_chromium_cdp, terminate_process_group
from wasm_asset_cache import ensure_wasm_assets


def _msg_id_for_env(env_b64: str) -> str:
    env_bytes = base64.b64decode(env_b64, validate=True)
    return hashlib.sha256(env_bytes).hexdigest()


def _start_static_server(root: Path) -> tuple[http.server.ThreadingHTTPServer, threading.Thread]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _format_cdp_tail(*, console_lines: list[str], exception_lines: list[str]) -> str:
    chunks: list[str] = []
    if console_lines:
        chunks.append("console tail:\n" + "\n".join(console_lines))
    if exception_lines:
        chunks.append("exceptions tail:\n" + "\n".join(exception_lines))
    if not chunks:
        return "cdp logs: <none captured>"
    return "cdp logs:\n" + "\n".join(chunks)


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


def _stash_take_first(stash: Deque[dict], predicate: Callable[[dict], bool]) -> Optional[dict]:
    for index, payload in enumerate(stash):
        if predicate(payload):
            del stash[index]
            return payload
    return None


def _stash_append(stash: Deque[dict], payload: dict, *, max_size: int = 200) -> None:
    stash.append(payload)
    while len(stash) > max_size:
        stash.popleft()


async def _ws_recv_until(
    ws,
    *,
    timeout_s: float,
    predicate: Callable[[dict], bool],
    stash: Deque[dict],
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    stashed = _stash_take_first(stash, predicate)
    if stashed is not None:
        return stashed
    while True:
        payload = await _ws_receive_payload(ws, deadline=deadline)
        if predicate(payload):
            return payload
        _stash_append(stash, payload)


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
        timeout_s=WS_READY_TIMEOUT_S,
        predicate=lambda payload: payload.get("t") == "session.ready",
        stash=deque(),
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


async def _ws_wait_for_ack(ws, *, request_id: str, timeout_s: float, stash: Deque[dict]) -> int:
    payload = await _ws_recv_until(
        ws,
        timeout_s=timeout_s,
        predicate=lambda message: message.get("t") == "conv.acked" and message.get("id") == request_id,
        stash=stash,
    )
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("seq"), int):
        raise AssertionError(f"Unexpected ack payload: {payload}")
    return body["seq"]


async def _ws_wait_for_event(
    ws,
    *,
    conv_id: str,
    expected_seq: int,
    timeout_s: float,
    stash: Deque[dict],
) -> dict:
    payload = await _ws_recv_until(
        ws,
        timeout_s=timeout_s,
        predicate=lambda message: message.get("t") == "conv.event"
        and isinstance(message.get("body"), dict)
        and message["body"].get("conv_id") == conv_id
        and message["body"].get("seq") == expected_seq,
        stash=stash,
    )
    return payload


async def _ws_assert_no_conv_event(ws, *, conv_id: str, timeout_s: float, stash: Deque[dict]) -> None:
    forbidden = (
        lambda message: message.get("t") == "conv.event"
        and isinstance(message.get("body"), dict)
        and message["body"].get("conv_id") == conv_id
    )
    stashed_forbidden = _stash_take_first(stash, forbidden)
    if stashed_forbidden is not None:
        raise AssertionError(f"Unexpected conv.event rebroadcast: {stashed_forbidden}")

    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        try:
            payload = await _ws_receive_payload(ws, deadline=deadline)
        except asyncio.TimeoutError:
            return
        if forbidden(payload):
            raise AssertionError(f"Unexpected conv.event rebroadcast: {payload}")
        _stash_append(stash, payload)


class _FakeWSMessage:
    def __init__(self, payload: dict):
        self.type = WSMsgType.TEXT
        self.data = json.dumps(payload)


class _FakeWS:
    def __init__(self, payloads: list[dict]):
        self._messages = [_FakeWSMessage(payload) for payload in payloads]

    async def receive(self, timeout=None):  # noqa: ANN001 - test fake mirrors aiohttp API
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(timeout if timeout is not None else 0)
        raise asyncio.TimeoutError

    async def pong(self):
        return None

    def exception(self):
        return None


class WebsocketStashRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_event_assertion_stashes_other_conversation_frames(self) -> None:
        room_event = {
            "v": 1,
            "t": "conv.event",
            "body": {"conv_id": "room-conv", "seq": 4, "env": "room-env"},
        }
        ws = _FakeWS([room_event])
        stash: Deque[dict] = deque()

        await _ws_assert_no_conv_event(ws, conv_id="dm-conv", timeout_s=0.01, stash=stash)

        recovered = await _ws_wait_for_event(
            ws,
            conv_id="room-conv",
            expected_seq=4,
            timeout_s=0.01,
            stash=stash,
        )
        self.assertEqual(recovered, room_event)


async def _cdp_wait_for_sentinel(ws_url: str, page_url: str, timeout_s: float) -> None:
    console_lines: list[str] = []
    exception_lines: list[str] = []
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
                    console_tail = console_lines[-20:]
                    exception_tail = exception_lines[-20:]
                    raise AssertionError(
                        "Timed out waiting for browser sentinel; "
                        f"cdp_ws_url={ws_url}; cdp_state={cdp_state}; "
                        f"{_format_cdp_tail(console_lines=console_tail, exception_lines=exception_tail)}"
                    )
                msg = await ws.receive(timeout=remaining)
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except ValueError:
                        continue
                else:
                    continue
                method = payload.get("method")
                if method == "Runtime.consoleAPICalled":
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
                            console_lines.append(value)
                            if len(console_lines) > 50:
                                console_lines = console_lines[-50:]
                            console_tail = console_lines[-20:]
                            exception_tail = exception_lines[-20:]
                            raise AssertionError(
                                f"{value}\n"
                                f"{_format_cdp_tail(console_lines=console_tail, exception_lines=exception_tail)}"
                            )
                    if console_text:
                        console_lines.append(console_text)
                        if len(console_lines) > 50:
                            console_lines = console_lines[-50:]
                elif method == "Runtime.exceptionThrown":
                    params = payload.get("params")
                    if not isinstance(params, dict):
                        continue
                    details = params.get("exceptionDetails", {})
                    if not isinstance(details, dict):
                        continue
                    exception = details.get("exception", {})
                    if isinstance(exception, dict):
                        description = exception.get("description") or details.get("text") or "exception"
                    else:
                        description = details.get("text") or "exception"
                    exception_lines.append(str(description))
                    if len(exception_lines) > 50:
                        exception_lines = exception_lines[-50:]


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
        stash: Deque[dict] = deque()

        dm_welcome_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["dm"],
            expected_seq=expected_seq["dm"],
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
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
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
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
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
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
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
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
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
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
        dm_reply_seq = await _ws_wait_for_ack(
            ws,
            request_id="dm-app-bob",
            timeout_s=WS_ACK_TIMEOUT_S,
            stash=stash,
        )
        self.assertEqual(dm_reply_seq, expected_seq["dm"] + 1)
        expected_seq["dm"] += 1
        await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["dm"],
            expected_seq=expected_seq["dm"],
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
        )

        await _ws_assert_no_conv_event(
            ws,
            conv_id=conv_ids["dm"],
            timeout_s=WS_NO_EVENT_TIMEOUT_S,
            stash=stash,
        )

        expected_seq["room"] += 1
        room_app_event = await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["room"],
            expected_seq=expected_seq["room"],
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
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
        room_reply_seq = await _ws_wait_for_ack(
            ws,
            request_id="room-app-bob",
            timeout_s=WS_ACK_TIMEOUT_S,
            stash=stash,
        )
        self.assertEqual(room_reply_seq, expected_seq["room"] + 1)
        expected_seq["room"] += 1
        await _ws_wait_for_event(
            ws,
            conv_id=conv_ids["room"],
            expected_seq=expected_seq["room"],
            timeout_s=WS_EVENT_TIMEOUT_S,
            stash=stash,
        )

    async def test_forbidden_subscribe_returns_error_frame(self) -> None:
        """Document protocol expectation used by browser smoke fail-fast logic.

        If a client subscribes to a conversation where it has no membership, gateway emits
        an explicit error frame with code=forbidden. The browser smoke test treats that
        frame as terminal rather than waiting for later acks/events.
        """
        alice_auth = "auth-alice-forbidden"
        bob_auth = "auth-bob-forbidden"
        alice_ready = await self._start_session_http(auth_token=alice_auth, device_id="dev-alice-forbidden")
        await self._start_session_http(auth_token=bob_auth, device_id="dev-bob-forbidden")

        conv_id = "conv_forbidden_subscribe"
        await self._create_room(alice_ready["session_token"], conv_id)

        bob_ws = await _ws_open_session(self.client, "dev-bob-forbidden", bob_auth)
        stash: Deque[dict] = deque()
        try:
            await _ws_subscribe(bob_ws, conv_id=conv_id, from_seq=1)
            error_payload = await _ws_recv_until(
                bob_ws,
                timeout_s=WS_ACK_TIMEOUT_S,
                predicate=lambda message: message.get("t") == "error",
                stash=stash,
            )
            body = error_payload.get("body") if isinstance(error_payload, dict) else None
            self.assertIsInstance(body, dict)
            self.assertEqual(body.get("code"), "forbidden")
        finally:
            await bob_ws.close()

    async def test_browser_wasm_cli_coexist_smoke(self) -> None:
        chromium_bin = find_chromium()
        if not chromium_bin:
            raise unittest.SkipTest("Chromium not available in PATH")

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

        chromium_proc: Optional[subprocess.Popen[str]] = None
        static_server: Optional[http.server.ThreadingHTTPServer] = None
        static_thread: Optional[threading.Thread] = None
        bob_ws = None

        try:
            with (
                tempfile.TemporaryDirectory(prefix="bob-dm-") as bob_dm_dir,
                tempfile.TemporaryDirectory(prefix="bob-room-") as bob_room_dir,
                tempfile.TemporaryDirectory(prefix="browser-static-") as static_dir,
                tempfile.TemporaryDirectory(prefix="chromium-user-") as chrome_profile,
            ):
                bob_dm_dir = Path(bob_dm_dir)
                bob_room_dir = Path(bob_room_dir)
                static_dir = Path(static_dir)
                chrome_profile = Path(chrome_profile)

                cdp_port = find_free_port()
                chromium_proc, cdp_ws_url = start_chromium_cdp(
                    chromium_bin,
                    cdp_port=cdp_port,
                    profile_dir=str(chrome_profile),
                    timeout_s=2.5,
                )

                bob_ws = await _ws_open_session(self.client, "dev-bob", bob_auth)
                for conv_id in conv_ids.values():
                    await _ws_subscribe(bob_ws, conv_id=conv_id, from_seq=1)

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

                cache_dir = Path(tempfile.gettempdir()) / "phase5-wasm-cache"
                ensure_wasm_assets(
                    wasm_exec_path=WASM_EXEC_SRC,
                    wasm_path=WASM_PATH,
                    tools_dir=WASM_MODULE_DIR,
                    cache_dir=cache_dir,
                )

                shutil.copy(WASM_EXEC_SRC, static_dir / "wasm_exec.js")
                shutil.copy(WASM_PATH, static_dir / "mls_harness.wasm")

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
  const recentMessages = [];
  const MAX_RECENT_MESSAGES = 30;
  let wsClosed = false;
  let wsCloseReason = null;
  let lastError = null;
  const summarizePayload = (payload) => {
    if (!payload || typeof payload !== 'object') {
      return { t: typeof payload };
    }
    const body = payload.body && typeof payload.body === 'object' ? payload.body : {};
    return {
      t: typeof payload.t === 'string' ? payload.t : null,
      id: typeof payload.id === 'string' ? payload.id : null,
      code: typeof body.code === 'string' ? body.code : null,
      message: typeof body.message === 'string' ? body.message : null,
      conv_id: typeof body.conv_id === 'string' ? body.conv_id : null,
      seq: Number.isInteger(body.seq) ? body.seq : null,
    };
  };
  const recentMessagesSummary = () => {
    const compact = JSON.stringify(recentMessages);
    const MAX_SUMMARY_LEN = 2200;
    if (compact.length <= MAX_SUMMARY_LEN) {
      return compact;
    }
    return compact.slice(0, MAX_SUMMARY_LEN) + '...<truncated>';
  };
  const setTerminalError = (err) => {
    if (!lastError) {
      lastError = err;
    }
    while (waiters.length) {
      const waiter = waiters.shift();
      waiter.reject(lastError);
    }
  };
  const maybeFailOnGatewayError = (payload) => {
    if (!payload || payload.t !== 'error') {
      return;
    }
    const body = payload.body && typeof payload.body === 'object' ? payload.body : {};
    const code = typeof body.code === 'string' ? body.code : 'unknown';
    const message = typeof body.message === 'string' ? body.message : 'no message';
    setTerminalError(new Error(`gateway error: ${code}: ${message}`));
  };
  const dispatch = (payload) => {
    recentMessages.push(summarizePayload(payload));
    if (recentMessages.length > MAX_RECENT_MESSAGES) {
      recentMessages.shift();
    }
    maybeFailOnGatewayError(payload);
    if (lastError) {
      return;
    }
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
  const waitFor = (label, predicate, timeout_ms) => new Promise((resolve, reject) => {
    if (lastError) {
      reject(lastError);
      return;
    }
    if (wsClosed) {
      reject(new Error(`websocket closed before ${label}: ${wsCloseReason || 'no reason'}`));
      return;
    }
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
      reject(new Error(`timeout waiting for ws message (${label}); recent=${recentMessagesSummary()}`));
    }, timeout_ms);
    waiters.push({
      predicate,
      resolve: (payload) => {
        clearTimeout(timeout);
        resolve(payload);
      },
      reject: (err) => {
        clearTimeout(timeout);
        reject(err);
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
  const handleWsError = () => {
    wsClosed = true;
    wsCloseReason = 'ws error';
    setTerminalError(new Error('websocket error event'));
  };
  ws.onerror = handleWsError;
  ws.onclose = (event) => {
    wsClosed = true;
    const reason = event && event.reason ? event.reason : 'no reason';
    const code = event && Number.isInteger(event.code) ? event.code : 'unknown';
    wsCloseReason = `code=${code} reason=${reason}`;
    setTerminalError(new Error(`websocket closed: ${wsCloseReason}`));
  };
  await new Promise((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.addEventListener('error', () => reject(new Error('ws error opening connection')), { once: true });
  });

  const send = async (body) => {
    ws.send(JSON.stringify(body));
  };

  const WS_WAIT_TIMEOUT_MS = 15000;

  const sendWithAck = async (body) => {
    await send(body);
    const ack = await waitFor(
      `conv.acked ${body.id}`,
      (payload) => payload.t === 'conv.acked' && payload.id === body.id,
      WS_WAIT_TIMEOUT_MS,
    );
    return ack.body.seq;
  };

  const expectEvent = async (conv_id, seq) => {
    const event = await waitFor(
      `conv.event ${conv_id}#${seq}`,
      (payload) => payload.t === 'conv.event'
        && payload.body
        && payload.body.conv_id === conv_id
        && payload.body.seq === seq,
      WS_WAIT_TIMEOUT_MS,
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
    await waitFor('session.ready', (msg) => msg.t === 'session.ready', WS_WAIT_TIMEOUT_MS);

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

    const dm_reply_event = await waitFor(
      'dm reply event',
      (message) => message.t === 'conv.event'
        && message.body
        && message.body.conv_id === payload.conv_ids.dm
        && message.body.seq === dm_seq + 1,
      WS_WAIT_TIMEOUT_MS,
    );
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

    const room_reply_event = await waitFor(
      'room reply event',
      (message) => message.t === 'conv.event'
        && message.body
        && message.body.conv_id === payload.conv_ids.room
        && message.body.seq === room_seq + 1,
      WS_WAIT_TIMEOUT_MS,
    );
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

                bob_task = asyncio.create_task(
                    self._bob_flow(
                        ws=bob_ws,
                        conv_ids=conv_ids,
                        bob_dm_dir=bob_dm_dir,
                        bob_room_dir=bob_room_dir,
                    )
                )
                try:
                    await _cdp_wait_for_sentinel(cdp_ws_url, page_url, timeout_s=30.0)
                    await bob_task
                except Exception:
                    bob_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await bob_task
                    raise

        finally:
            if bob_ws is not None:
                await bob_ws.close()
            if static_server is not None:
                static_server.shutdown()
                static_server.server_close()
            if static_thread is not None:
                static_thread.join(timeout=2.0)
            if chromium_proc is not None:
                terminate_process_group(chromium_proc, label="chromium")


if __name__ == "__main__":
    unittest.main()
