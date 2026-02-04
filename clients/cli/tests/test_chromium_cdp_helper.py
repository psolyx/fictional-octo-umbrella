import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import sys

HELPERS_DIR = Path(__file__).resolve().parent / "helpers"
sys.path.insert(0, str(HELPERS_DIR))
from chromium_cdp import _wait_for_cdp_url  # noqa: E402


class _DummyProc:
    def poll(self) -> Optional[int]:
        return None


class _CDPState:
    def __init__(self, *, list_payloads: list[list[dict]], version_payload: dict) -> None:
        self.list_payloads = list_payloads
        self.version_payload = version_payload
        self.list_calls = 0

    def next_list_payload(self) -> list[dict]:
        payload = self.list_payloads[min(self.list_calls, len(self.list_payloads) - 1)]
        self.list_calls += 1
        return payload


class _CDPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        state: _CDPState = self.server.cdp_state
        if self.path == "/json/version":
            payload = state.version_payload
            self._send_json(payload)
            return
        if self.path in ("/json/list", "/json"):
            payload = state.next_list_payload()
            self._send_json(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - matches base signature
        return

    def _send_json(self, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _CDPTestServer:
    def __init__(self, state: _CDPState) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _CDPRequestHandler)
        self._server.cdp_state = state
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=1.0)
        self._server.server_close()


class ChromiumCDPHelperTests(unittest.TestCase):
    def _run_wait_for_cdp(
        self, list_payloads: list[list[dict]], *, timeout_s: float = 1.0
    ) -> tuple[str, int]:
        state = _CDPState(
            list_payloads=list_payloads,
            version_payload={
                "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/XYZ"
            },
        )
        server = _CDPTestServer(state)
        server.start()
        try:
            return _wait_for_cdp_url(_DummyProc(), server.port, timeout_s), server.port
        finally:
            server.stop()

    def test_wait_for_cdp_prefers_page_target(self) -> None:
        ws_url, _ = self._run_wait_for_cdp(
            [
                [
                    {
                        "type": "page",
                        "url": "about:blank",
                        "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/ABC",
                    }
                ]
            ]
        )
        self.assertEqual(ws_url, "ws://127.0.0.1/devtools/page/ABC")

    def test_wait_for_cdp_polls_until_page_target_available(self) -> None:
        start = time.time()
        ws_url, _ = self._run_wait_for_cdp(
            [
                [],
                [
                    {
                        "type": "page",
                        "url": "about:blank",
                        "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/DEF",
                    }
                ],
            ],
            timeout_s=1.5,
        )
        self.assertEqual(ws_url, "ws://127.0.0.1/devtools/page/DEF")
        self.assertGreater(time.time() - start, 0.0)

    def test_wait_for_cdp_synthesizes_ws_url_when_missing(self) -> None:
        ws_url, port = self._run_wait_for_cdp(
            [
                [
                    {
                        "type": "page",
                        "url": "about:blank",
                        "id": "GHI",
                    }
                ]
            ]
        )
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/GHI")
