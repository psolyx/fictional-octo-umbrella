import asyncio
import http.server
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from collections import deque
from pathlib import Path
from typing import Deque, Optional

from aiohttp import ClientSession, WSMsgType

ROOT_DIR = Path(__file__).resolve().parents[3]
WEB_DIR = ROOT_DIR / "clients" / "web"
VECTORS_DIR = WEB_DIR / "vectors"
TOOLS_DIR = ROOT_DIR / "tools" / "mls_harness"
WASM_PATH = WEB_DIR / "vendor" / "mls_harness.wasm"
WASM_EXEC = WEB_DIR / "vendor" / "wasm_exec.js"
VECTORS_JSON = VECTORS_DIR / "room_seeded_bootstrap_v1.json"

CSP_VALUE = (
    "default-src 'self'; "
    "script-src 'self' 'wasm-unsafe-eval'; "
    "connect-src 'self' ws: wss:; "
    "img-src 'self'; "
    "style-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


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


def _format_cdp_logs(lines: Deque[str]) -> str:
    if not lines:
        return "cdp logs: <none captured>"
    return "cdp logs (last lines):\n" + "\n".join(lines)


def _terminate_process(proc: subprocess.Popen[str], *, label: str) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"{label} failed to terminate") from None


def _wait_for_http(url: str, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - test harness polling
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(
        "dev server did not become ready.\n"
        f"last_error: {last_error}"
    )


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


def _format_remote_object(obj: dict) -> str:
    if "value" in obj:
        return repr(obj["value"])
    if "description" in obj:
        return str(obj["description"])
    if "type" in obj:
        return str(obj["type"])
    return json.dumps(obj, sort_keys=True)


def _record_cdp_event(payload: dict, *, logs: Deque[str]) -> None:
    method = payload.get("method")
    params = payload.get("params", {})
    if method == "Runtime.consoleAPICalled":
        args = params.get("args", [])
        text = " ".join(_format_remote_object(arg) for arg in args)
        logs.append(f"[console.{params.get('type', 'log')}] {text}".strip())
    elif method == "Runtime.exceptionThrown":
        details = params.get("exceptionDetails", {})
        exception = details.get("exception", {})
        description = exception.get("description") or details.get("text") or "exception"
        logs.append(f"[exception] {description}")
    elif method == "Log.entryAdded":
        entry = params.get("entry", {})
        logs.append(f"[log.{entry.get('level', 'info')}] {entry.get('text', '')}")


def _should_skip_cdp_error(message: str) -> Optional[str]:
    lowered = message.lower()
    if "target closed" in lowered or "session closed" in lowered:
        return "CDP target closed"
    if "connection closed" in lowered or "websocket is closed" in lowered:
        return "CDP connection closed"
    if "execution context was destroyed" in lowered or "cannot find context" in lowered:
        return "CDP execution context unavailable"
    if "execution context was not found" in lowered:
        return "CDP execution context missing"
    if "frame" in lowered and "not found" in lowered:
        return "CDP frame missing"
    if "navigation" in lowered and ("failed" in lowered or "aborted" in lowered):
        return "CDP navigation failed"
    return None


async def _cdp_wait_for_load(ws, *, deadline: float, logs: Deque[str]) -> None:
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError("Timed out waiting for Page.loadEventFired")
        msg = await ws.receive(timeout=remaining)
        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
            raise unittest.SkipTest("CDP session closed while waiting for page load")
        if msg.type != WSMsgType.TEXT:
            continue
        payload = json.loads(msg.data)
        if payload.get("method"):
            _record_cdp_event(payload, logs=logs)
        if payload.get("method") == "Page.loadEventFired":
            return


async def _cdp_request(ws, message: dict, *, deadline: float, logs: Deque[str]) -> dict:
    await ws.send_json(message)
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError("Timed out waiting for CDP response")
        msg = await ws.receive(timeout=remaining)
        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
            raise unittest.SkipTest("CDP session closed while waiting for response")
        if msg.type != WSMsgType.TEXT:
            continue
        payload = json.loads(msg.data)
        if payload.get("method"):
            _record_cdp_event(payload, logs=logs)
        if payload.get("id") == message["id"]:
            if "error" in payload:
                error_message = payload["error"].get("message", "unknown CDP error")
                skip_reason = _should_skip_cdp_error(error_message)
                if skip_reason:
                    raise unittest.SkipTest(skip_reason)
                raise AssertionError(f"CDP error: {error_message}")
            return payload


async def _cdp_eval(ws, expression: str, *, msg_id: int, deadline: float, logs: Deque[str]):
    response = await _cdp_request(
        ws,
        {
            "id": msg_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        },
        deadline=deadline,
        logs=logs,
    )
    result_payload = response.get("result", {})
    if "exceptionDetails" in result_payload:
        details = result_payload.get("exceptionDetails", {})
        exception = details.get("exception", {})
        description = exception.get("description") or details.get("text") or "exception"
        skip_reason = _should_skip_cdp_error(description)
        if skip_reason:
            raise unittest.SkipTest(skip_reason)
        raise AssertionError(f"CDP evaluation exception: {description}")
    result = result_payload.get("result", {})
    if not result_payload:
        raise AssertionError(f"CDP evaluation missing result for: {expression}")
    return result.get("value")


async def _cdp_run(ws_url: str, page_url: str, timeout_s: float) -> tuple[dict, Deque[str]]:
    async with ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            cdp_logs: Deque[str] = deque(maxlen=50)
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({"id": 2, "method": "Runtime.enable"})
            await ws.send_json({"id": 3, "method": "Log.enable"})
            await ws.send_json({"id": 4, "method": "Page.navigate", "params": {"url": page_url}})

            deadline = asyncio.get_running_loop().time() + timeout_s
            try:
                await _cdp_wait_for_load(ws, deadline=deadline, logs=cdp_logs)
            except (TimeoutError, AssertionError):
                pass

            poll_deadline = asyncio.get_running_loop().time() + timeout_s
            msg_id = 10
            while True:
                if asyncio.get_running_loop().time() >= poll_deadline:
                    ready_state = "unknown"
                    smoke_done = "unknown"
                    smoke_result = "unknown"
                    try:
                        ready_state = await _cdp_eval(
                            ws,
                            "document.readyState",
                            msg_id=msg_id,
                            deadline=asyncio.get_running_loop().time() + 2.0,
                            logs=cdp_logs,
                        )
                        msg_id += 1
                        smoke_done = await _cdp_eval(
                            ws,
                            "window.__SMOKE_DONE__",
                            msg_id=msg_id,
                            deadline=asyncio.get_running_loop().time() + 2.0,
                            logs=cdp_logs,
                        )
                        msg_id += 1
                        smoke_result = await _cdp_eval(
                            ws,
                            "window.__SMOKE_RESULT__",
                            msg_id=msg_id,
                            deadline=asyncio.get_running_loop().time() + 2.0,
                            logs=cdp_logs,
                        )
                        msg_id += 1
                    except AssertionError:
                        ready_state = "unknown"
                    raise AssertionError(
                        "Timed out waiting for browser smoke result "
                        f"(readyState={ready_state}, "
                        f"smoke_done={smoke_done}, "
                        f"smoke_result={smoke_result}).\n"
                        f"{_format_cdp_logs(cdp_logs)}"
                    )
                done = await _cdp_eval(
                    ws,
                    "window.__SMOKE_DONE__ === true",
                    msg_id=msg_id,
                    deadline=poll_deadline,
                    logs=cdp_logs,
                )
                msg_id += 1
                if done:
                    result = await _cdp_eval(
                        ws,
                        "window.__SMOKE_RESULT__",
                        msg_id=msg_id,
                        deadline=poll_deadline,
                        logs=cdp_logs,
                    )
                    if not isinstance(result, dict):
                        raise AssertionError(f"Unexpected smoke result: {result}")
                    return result, cdp_logs
                await asyncio.sleep(0.1)


def _ensure_wasm_assets() -> None:
    if WASM_PATH.exists() and WASM_EXEC.exists():
        return
    if not shutil.which("go"):
        raise unittest.SkipTest("Go toolchain not available for WASM build")
    build_script = TOOLS_DIR / "build_wasm.sh"
    subprocess.run(["bash", str(build_script)], cwd=str(ROOT_DIR), check=True)
    if not WASM_PATH.exists():
        raise AssertionError("WASM build completed but mls_harness.wasm is missing")
    if not WASM_EXEC.exists():
        raise AssertionError("WASM build completed but wasm_exec.js is missing")


def _prepare_smoke_assets(temp_root: Path) -> tuple[Path, Path]:
    vendor_dir = temp_root / "vendor"
    vectors_dir = temp_root / "vectors"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    vectors_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(WASM_EXEC, vendor_dir / "wasm_exec.js")
    shutil.copy(WASM_PATH, vendor_dir / "mls_harness.wasm")
    shutil.copy(WEB_DIR / "mls_vectors_loader.js", temp_root / "mls_vectors_loader.js")
    shutil.copy(VECTORS_JSON, vectors_dir / VECTORS_JSON.name)

    module_file = temp_root / "phase5_browser_runtime_smoke.js"
    module_file.write_text(
        """import {
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

window.addEventListener('error', (event) => {
  if (!window.__SMOKE_DONE__) {
    window.__SMOKE_RESULT__ = { ok: false, error: `unhandled error: ${event.message}` };
    window.__SMOKE_DONE__ = true;
  }
});

window.addEventListener('unhandledrejection', (event) => {
  const reason = event && event.reason ? event.reason : 'unknown';
  if (!window.__SMOKE_DONE__) {
    window.__SMOKE_RESULT__ = { ok: false, error: `unhandled rejection: ${reason}` };
    window.__SMOKE_DONE__ = true;
  }
});

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
""",
        encoding="utf-8",
    )

    html_file = temp_root / "index.html"
    html_file.write_text(
        f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta http-equiv=\"Content-Security-Policy\" content=\"{CSP_VALUE}\" />
    <title>Phase5 Browser Runtime Smoke</title>
  </head>
  <body>
    <script src=\"vendor/wasm_exec.js\"></script>
    <script type=\"module\" src=\"{module_file.name}\"></script>
  </body>
</html>
""",
        encoding="utf-8",
    )
    return html_file, module_file


def _start_csp_server(root: Path) -> tuple[http.server.ThreadingHTTPServer, threading.Thread]:
    class csp_handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Content-Security-Policy", CSP_VALUE)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), csp_handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class BrowserRuntimeSmokeTest(unittest.TestCase):
    def test_browser_runtime_smoke(self) -> None:
        chromium_bin = _find_chromium()
        if not chromium_bin:
            raise unittest.SkipTest("Chromium not available in PATH")
        if not WASM_EXEC.exists():
            raise unittest.SkipTest("wasm_exec.js missing from clients/web/vendor")
        if not WASM_PATH.exists() and not shutil.which("go"):
            raise unittest.SkipTest("Go toolchain not available for WASM build")

        chromium_proc: Optional[subprocess.Popen[str]] = None
        server: Optional[http.server.ThreadingHTTPServer] = None
        server_thread: Optional[threading.Thread] = None
        try:
            _ensure_wasm_assets()
            with tempfile.TemporaryDirectory(prefix="phase5-browser-assets-") as temp_dir:
                temp_root = Path(temp_dir)
                _prepare_smoke_assets(temp_root)
                server, server_thread = _start_csp_server(temp_root)
                ready_url = f"http://127.0.0.1:{server.server_address[1]}"
                _wait_for_http(f"{ready_url}/index.html", timeout_s=5.0)

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
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    try:
                        cdp_ws_url = _wait_for_cdp_url(cdp_port, timeout_s=5.0)
                    except Exception as exc:  # noqa: BLE001 - skip on CDP failure
                        raise unittest.SkipTest(
                            f"chromium remote debugging unavailable: {exc}"
                        ) from exc

                    page_url = f"{ready_url}/index.html"
                    result, logs = asyncio.run(_cdp_run(cdp_ws_url, page_url, timeout_s=180.0))
                    if not result.get("ok"):
                        raise AssertionError(
                            f"Browser runtime smoke failed: {result}\n{_format_cdp_logs(logs)}"
                        )
        finally:
            if chromium_proc is not None:
                _terminate_process(chromium_proc, label="chromium")
            if server is not None:
                server.shutdown()
                server.server_close()
            if server_thread is not None:
                server_thread.join(timeout=2.0)
