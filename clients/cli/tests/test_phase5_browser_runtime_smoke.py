import asyncio
import json
import selectors
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from typing import Optional

from aiohttp import ClientSession, WSMsgType

ROOT_DIR = Path(__file__).resolve().parents[3]
WEB_DIR = ROOT_DIR / "clients" / "web"
DEV_SERVER = WEB_DIR / "tools" / "csp_dev_server.py"
WASM_PATH = WEB_DIR / "vendor" / "mls_harness.wasm"
WASM_EXEC = WEB_DIR / "vendor" / "wasm_exec.js"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _find_chromium() -> Optional[str]:
    candidates = [
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
    ]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def _wait_for_http(url: str, timeout_s: float, *, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + timeout_s
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        if process.poll() is not None:
            stderr_output = ""
            if process.stderr is not None:
                stderr_output = process.stderr.read()
            raise AssertionError(
                "dev server exited before becoming ready.\n"
                f"stderr:\n{stderr_output}"
            )
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - test harness polling
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"dev server did not become ready: {last_error}")


def _wait_for_ready_url(
    timeout_s: float,
    *,
    process: subprocess.Popen[str],
) -> str:
    deadline = time.time() + timeout_s
    selector = selectors.DefaultSelector()
    if process.stdout is None:
        raise AssertionError("dev server stdout unavailable")
    selector.register(process.stdout, selectors.EVENT_READ)
    stdout_lines = []
    try:
        while time.time() < deadline:
            if process.poll() is not None:
                stderr_output = ""
                if process.stderr is not None:
                    stderr_output = process.stderr.read()
                stdout_output = "".join(stdout_lines)
                raise AssertionError(
                    "dev server exited before becoming ready.\n"
                    f"stdout:\n{stdout_output}\n"
                    f"stderr:\n{stderr_output}"
                )
            events = selector.select(timeout=0.1)
            for key, _ in events:
                line = key.fileobj.readline()
                if not line:
                    continue
                stdout_lines.append(line)
                if line.startswith("READY "):
                    return line.split("READY ", 1)[1].strip()
    finally:
        selector.close()
    raise AssertionError("Timed out waiting for dev server readiness output")


def _wait_for_cdp_url(port: int, timeout_s: float) -> str:
    deadline = time.time() + timeout_s
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                ws_url = payload.get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url
        except Exception as exc:  # noqa: BLE001 - polling for CDP
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for Chromium DevTools URL: {last_error}")


async def _cdp_wait_for_load(ws, *, deadline: float) -> None:
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError("Timed out waiting for Page.loadEventFired")
        msg = await ws.receive(timeout=remaining)
        if msg.type != WSMsgType.TEXT:
            continue
        payload = json.loads(msg.data)
        if payload.get("method") == "Page.loadEventFired":
            return


async def _cdp_request(ws, message: dict, *, deadline: float) -> dict:
    await ws.send_json(message)
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError("Timed out waiting for CDP response")
        msg = await ws.receive(timeout=remaining)
        if msg.type != WSMsgType.TEXT:
            continue
        payload = json.loads(msg.data)
        if payload.get("id") == message["id"]:
            return payload


async def _cdp_eval(ws, expression: str, *, msg_id: int, deadline: float):
    response = await _cdp_request(
        ws,
        {
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        },
        deadline=deadline,
    )
    result = response.get("result", {}).get("result", {})
    return result.get("value")


async def _cdp_run(ws_url: str, page_url: str, timeout_s: float) -> dict:
    async with ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({"id": 2, "method": "Runtime.enable"})
            await ws.send_json({"id": 3, "method": "Page.navigate", "params": {"url": page_url}})

            deadline = asyncio.get_running_loop().time() + timeout_s
            await _cdp_wait_for_load(ws, deadline=deadline)

            poll_deadline = asyncio.get_running_loop().time() + timeout_s
            msg_id = 10
            while True:
                if asyncio.get_running_loop().time() >= poll_deadline:
                    raise AssertionError("Timed out waiting for browser smoke result")
                done = await _cdp_eval(ws, "window.__SMOKE_DONE__ === true", msg_id=msg_id, deadline=poll_deadline)
                msg_id += 1
                if done:
                    result = await _cdp_eval(ws, "window.__SMOKE_RESULT__", msg_id=msg_id, deadline=poll_deadline)
                    if not isinstance(result, dict):
                        raise AssertionError(f"Unexpected smoke result: {result}")
                    return result
                await asyncio.sleep(0.1)


class BrowserRuntimeSmokeTest(unittest.TestCase):
    def test_browser_runtime_smoke(self) -> None:
        chromium_bin = _find_chromium()
        if not chromium_bin:
            raise unittest.SkipTest("Chromium not available in PATH")
        if not WASM_EXEC.exists():
            raise unittest.SkipTest("wasm_exec.js missing from clients/web/vendor")
        if not WASM_PATH.exists() and not shutil.which("go"):
            raise unittest.SkipTest("Go toolchain not available for WASM build")

        html_file = None
        server_proc: Optional[subprocess.Popen[str]] = None
        chromium_proc: Optional[subprocess.Popen[str]] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".html",
                prefix="phase5_browser_runtime_smoke_",
                dir=WEB_DIR,
                delete=False,
            ) as temp_html:
                html_file = Path(temp_html.name)
                temp_html.write(
                    """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Phase5 Browser Runtime Smoke</title>
  </head>
  <body>
    <script src="vendor/wasm_exec.js"></script>
    <script type="module">
      import {
        verify_vectors_from_url,
        dm_create_participant,
        dm_init,
        dm_join,
        dm_commit_apply,
        dm_encrypt,
        dm_decrypt
      } from './mls_vectors_loader.js';

      window.__SMOKE_DONE__ = false;
      window.__SMOKE_RESULT__ = { ok: false, error: 'not started' };

      const bytes_to_base64 = (bytes) => {
        let output = '';
        const chunk = 8192;
        for (let i = 0; i < bytes.length; i += chunk) {
          output += String.fromCharCode(...bytes.subarray(i, i + chunk));
        }
        return btoa(output);
      };

      const require_ok = (result, label) => {
        if (!result || !result.ok) {
          const error_text = result && result.error ? result.error : 'unknown error';
          throw new Error(`${label} failed: ${error_text}`);
        }
        return result;
      };

      const set_done = (ok, error_text) => {
        if (ok) {
          window.__SMOKE_RESULT__ = { ok: true };
        } else {
          window.__SMOKE_RESULT__ = { ok: false, error: error_text };
        }
        window.__SMOKE_DONE__ = true;
      };

      const run = async () => {
        const vectors = await verify_vectors_from_url('./vectors/room_seeded_bootstrap_v1.json');
        if (!vectors || vectors.ok !== true) {
          throw new Error(`vector verify failed: ${JSON.stringify(vectors)}`);
        }

        const group_id_bytes = new Uint8Array(32);
        crypto.getRandomValues(group_id_bytes);
        const group_id_b64 = bytes_to_base64(group_id_bytes);

        const alice = require_ok(await dm_create_participant('alice', 101), 'alice participant');
        const bob = require_ok(await dm_create_participant('bob', 202), 'bob participant');
        const init = require_ok(
          await dm_init(alice.participant_b64, bob.keypackage_b64, group_id_b64, 303),
          'dm init'
        );
        const bob_join = require_ok(await dm_join(bob.participant_b64, init.welcome_b64), 'dm join');
        const alice_commit = require_ok(
          await dm_commit_apply(init.participant_b64, init.commit_b64),
          'alice commit apply'
        );
        const bob_commit = require_ok(
          await dm_commit_apply(bob_join.participant_b64, init.commit_b64),
          'bob commit apply'
        );

        const outbound = require_ok(await dm_encrypt(alice_commit.participant_b64, 'hello bob'), 'encrypt a->b');
        const inbound = require_ok(await dm_decrypt(bob_commit.participant_b64, outbound.ciphertext_b64), 'decrypt a->b');
        if (inbound.plaintext !== 'hello bob') {
          throw new Error(`unexpected a->b plaintext: ${inbound.plaintext}`);
        }

        const outbound2 = require_ok(await dm_encrypt(bob_commit.participant_b64, 'hello alice'), 'encrypt b->a');
        const inbound2 = require_ok(
          await dm_decrypt(alice_commit.participant_b64, outbound2.ciphertext_b64),
          'decrypt b->a'
        );
        if (inbound2.plaintext !== 'hello alice') {
          throw new Error(`unexpected b->a plaintext: ${inbound2.plaintext}`);
        }
      };

      run().then(
        () => set_done(true, ''),
        (error) => set_done(false, error && error.message ? error.message : String(error))
      );
    </script>
  </body>
</html>
"""
                )

            server_proc = subprocess.Popen(
                [
                    sys.executable,
                    str(DEV_SERVER),
                    "--serve",
                    "--build-wasm-if-missing",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "0",
                ],
                cwd=str(ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            ready_url = _wait_for_ready_url(timeout_s=10.0, process=server_proc)
            _wait_for_http(
                f"{ready_url}/index.html",
                timeout_s=10.0,
                process=server_proc,
            )

            cdp_port = _find_free_port()
            with tempfile.TemporaryDirectory(prefix="chromium-profile-") as profile_dir:
                chromium_proc = subprocess.Popen(
                    [
                        chromium_bin,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-background-networking",
                        "--disable-default-apps",
                        "--disable-extensions",
                        "--disable-sync",
                        "--metrics-recording-only",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--mute-audio",
                        "--disable-popup-blocking",
                        "--disable-dev-shm-usage",
                        "--remote-debugging-address=127.0.0.1",
                        f"--remote-debugging-port={cdp_port}",
                        f"--user-data-dir={profile_dir}",
                        "about:blank",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    cdp_ws_url = _wait_for_cdp_url(cdp_port, timeout_s=5.0)
                except Exception as exc:  # noqa: BLE001 - skip on CDP failure
                    raise unittest.SkipTest(f"chromium remote debugging unavailable: {exc}") from exc

                page_url = f"{ready_url}/{html_file.name}"
                result = asyncio.run(_cdp_run(cdp_ws_url, page_url, timeout_s=20.0))
                if not result.get("ok"):
                    raise AssertionError(f"Browser runtime smoke failed: {result}")
        finally:
            if chromium_proc is not None:
                chromium_proc.terminate()
                try:
                    chromium_proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    chromium_proc.kill()
            if server_proc is not None:
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
            if html_file is not None and html_file.exists():
                html_file.unlink()
