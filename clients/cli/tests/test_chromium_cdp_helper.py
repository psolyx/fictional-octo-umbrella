import json
import os
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers.chromium_cdp import (
    _fetch_cdp_targets,
    _select_cdp_page_target,
    _wait_for_cdp_url,
    find_chromium,
    find_free_port,
)


class _DummyProc:
    def poll(self) -> None:
        return None


class _CdpState:
    def __init__(
        self,
        *,
        version_payload: dict,
        list_payloads: list[list[dict]],
        json_payloads: list[object] | None = None,
        list_statuses: list[int] | None = None,
        json_statuses: list[int] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._list_payloads = list_payloads
        self._json_payloads = json_payloads or list_payloads
        self._list_statuses = list_statuses or [200]
        self._json_statuses = json_statuses or [200]
        self._list_calls = 0
        self._json_calls = 0
        self._list_status_calls = 0
        self._json_status_calls = 0
        self.version_payload = version_payload

    def next_list_payload(self) -> list[dict]:
        with self._lock:
            index = min(self._list_calls, len(self._list_payloads) - 1)
            payload = self._list_payloads[index]
            self._list_calls += 1
            return payload

    def next_list_status(self) -> int:
        with self._lock:
            index = min(self._list_status_calls, len(self._list_statuses) - 1)
            status = self._list_statuses[index]
            self._list_status_calls += 1
            return status

    def next_json_payload(self) -> object:
        with self._lock:
            index = min(self._json_calls, len(self._json_payloads) - 1)
            payload = self._json_payloads[index]
            self._json_calls += 1
            return payload

    def next_json_status(self) -> int:
        with self._lock:
            index = min(self._json_status_calls, len(self._json_statuses) - 1)
            status = self._json_statuses[index]
            self._json_status_calls += 1
            return status

    @property
    def list_calls(self) -> int:
        with self._lock:
            return self._list_calls

    @property
    def json_calls(self) -> int:
        with self._lock:
            return self._json_calls


def _start_cdp_server(state: _CdpState, port: int) -> tuple[ThreadingHTTPServer, threading.Thread]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            if self.path == "/json/version":
                payload = state.version_payload
                self._write_json(payload)
                return
            if self.path == "/json/list":
                status = state.next_list_status()
                if status != 200:
                    self.send_response(status)
                    self.end_headers()
                    return
                payload = state.next_list_payload()
                self._write_json(payload)
                return
            if self.path == "/json":
                status = state.next_json_status()
                if status != 200:
                    self.send_response(status)
                    self.end_headers()
                    return
                payload = state.next_json_payload()
                self._write_json(payload)
                return
            self.send_response(404)
            self.end_headers()

        def _write_json(self, payload: object) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003 - shadow builtin
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class ChromiumCdpHelperTests(unittest.TestCase):
    """Hermetic CDP helper coverage for page-target discovery."""

    def test_select_picks_first_page_when_no_about_blank(self) -> None:
        port = find_free_port()
        targets = [
            {
                "type": "page",
                "url": "https://example.com",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/FIRST",
            },
            {
                "type": "page",
                "url": "https://example.org",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/SECOND",
            },
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/FIRST")

    def test_find_chromium_prefers_env_override(self) -> None:
        original_bin = os.environ.get("CHROMIUM_BIN")
        original_path = os.environ.get("CHROMIUM_PATH")
        try:
            os.environ["CHROMIUM_BIN"] = "/bin/sh"
            os.environ.pop("CHROMIUM_PATH", None)
            resolved = find_chromium()
            self.assertEqual(resolved, "/bin/sh")
        finally:
            if original_bin is None:
                os.environ.pop("CHROMIUM_BIN", None)
            else:
                os.environ["CHROMIUM_BIN"] = original_bin
            if original_path is None:
                os.environ.pop("CHROMIUM_PATH", None)
            else:
                os.environ["CHROMIUM_PATH"] = original_path

    def test_select_uses_synthesized_id_when_websocket_missing(self) -> None:
        port = find_free_port()
        targets = [{"type": "page", "url": "https://example.net", "id": "SYNTH"}]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/SYNTH")

    def test_select_skips_targets_without_id_or_websocket(self) -> None:
        port = find_free_port()
        targets = [
            {"type": "page", "url": "about:blank"},
            {
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/FOUND",
            },
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/FOUND")

    def test_select_keeps_first_candidate_when_no_about_blank(self) -> None:
        port = find_free_port()
        targets = [
            {
                "type": "page",
                "url": "https://alpha.example",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/ALPHA",
            },
            {
                "type": "page",
                "url": "https://beta.example",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/BETA",
            },
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/ALPHA")

    def test_select_returns_none_for_empty_target_list(self) -> None:
        ws_url = _select_cdp_page_target([], 9222)
        self.assertIsNone(ws_url)

    def test_select_skips_non_page_targets(self) -> None:
        port = find_free_port()
        targets = [
            {"type": "service_worker", "id": "SW1"},
            {"type": "shared_worker", "id": "SW2"},
            {"type": "page", "url": "about:blank", "id": "PAGE"},
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/PAGE")

    def test_select_prefers_about_blank_when_multiple_pages(self) -> None:
        port = find_free_port()
        targets = [
            {"type": "page", "url": "https://example.com", "id": "AAA"},
            {"type": "page", "url": "about:blank", "id": "BBB"},
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/BBB")

    def test_select_ignores_browser_websocket_urls(self) -> None:
        port = find_free_port()
        targets = [
            {
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/IGNORE",
            },
            {
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/KEEP",
            },
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/KEEP")

    def test_select_returns_none_when_only_browser_websocket(self) -> None:
        port = find_free_port()
        targets = [
            {
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/ONLY",
                "id": "ONLY",
            }
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertIsNone(ws_url)

    def test_select_skips_browser_websocket_then_uses_synthesized(self) -> None:
        port = find_free_port()
        targets = [
            {
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/IGNORE",
                "id": "IGNORE",
            },
            {"type": "page", "url": "about:blank", "id": "GOOD"},
        ]
        ws_url = _select_cdp_page_target(targets, port)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/GOOD")

    def test_select_returns_none_without_page_targets(self) -> None:
        ws_url = _select_cdp_page_target([{"type": "service_worker"}], 9222)
        self.assertIsNone(ws_url)

    def test_fetch_targets_falls_back_to_json_endpoint(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/XYZ"},
            list_payloads=[{"not": "a list"}],  # force /json/list to be skipped
            json_payloads=[[{"type": "page", "url": "about:blank", "id": "FALLBACK"}]],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            targets = _fetch_cdp_targets(port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(targets[0]["id"], "FALLBACK")
        self.assertEqual(state.list_calls, 1)
        self.assertEqual(state.json_calls, 1)

    def test_fetch_targets_prefers_json_list_when_available(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/XYZ"},
            list_payloads=[[{"type": "page", "url": "about:blank", "id": "LIST"}]],
            json_payloads=[[{"type": "page", "url": "about:blank", "id": "JSON"}]],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            targets = _fetch_cdp_targets(port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(targets[0]["id"], "LIST")
        self.assertEqual(state.list_calls, 1)
        self.assertEqual(state.json_calls, 0)

    def test_fetch_targets_handles_list_http_error_then_json(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/XYZ"},
            list_payloads=[[{"type": "page", "url": "about:blank", "id": "LIST"}]],
            json_payloads=[[{"type": "page", "url": "about:blank", "id": "JSON"}]],
            list_statuses=[500],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            targets = _fetch_cdp_targets(port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(targets[0]["id"], "JSON")
        self.assertEqual(state.list_calls, 0)
        self.assertEqual(state.json_calls, 1)

    def test_fetch_targets_handles_json_http_error(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/XYZ"},
            list_payloads=[{"not": "a list"}],
            json_payloads=[[{"type": "page", "url": "about:blank", "id": "JSON"}]],
            json_statuses=[500],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            with self.assertRaises(urllib.error.HTTPError):
                _fetch_cdp_targets(port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)

    def test_fetch_targets_raises_when_no_lists(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/XYZ"},
            list_payloads=[{"not": "a list"}],
            json_payloads=[{"still": "not a list"}],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            with self.assertRaises(RuntimeError):
                _fetch_cdp_targets(port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)

    def test_selects_page_websocket_from_json_list(self) -> None:
        port = find_free_port()
        page_ws = f"ws://127.0.0.1:{port}/devtools/page/ABC"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[[{"type": "page", "url": "about:blank", "webSocketDebuggerUrl": page_ws}]],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, page_ws)
        self.assertIn("/devtools/page/", ws_url)

    def test_polls_until_page_target_appears(self) -> None:
        port = find_free_port()
        page_ws = f"ws://127.0.0.1:{port}/devtools/page/DEF"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[
                [],
                [{"type": "other"}],
                [{"type": "page", "url": "about:blank", "webSocketDebuggerUrl": page_ws}],
            ],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=1.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, page_ws)
        self.assertGreaterEqual(state.list_calls, 2)

    def test_synthesizes_page_websocket_when_missing(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[[{"type": "page", "url": "about:blank", "id": "GHI"}]],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/GHI")

    def test_wait_for_cdp_url_falls_back_to_json_endpoint(self) -> None:
        port = find_free_port()
        page_ws = f"ws://127.0.0.1:{port}/devtools/page/JSON"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[{"not": "a list"}],
            json_payloads=[[{"type": "page", "url": "about:blank", "webSocketDebuggerUrl": page_ws}]],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, page_ws)

    def test_wait_for_cdp_url_uses_first_valid_page_target(self) -> None:
        port = find_free_port()
        page_ws = f"ws://127.0.0.1:{port}/devtools/page/PRIMARY"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[
                [
                    {"type": "page", "url": "https://example.org"},
                    {"type": "page", "url": "https://example.com", "webSocketDebuggerUrl": page_ws},
                    {"type": "page", "url": "https://example.net", "id": "SECONDARY"},
                ]
            ],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, page_ws)

    def test_wait_for_cdp_url_uses_synthesized_page_after_invalid(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[
                [{"type": "page", "url": "https://example.org"}],
                [{"type": "page", "url": "about:blank", "id": "SYNTH2"}],
            ],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=1.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, f"ws://127.0.0.1:{port}/devtools/page/SYNTH2")

    def test_wait_for_cdp_url_prefers_about_blank_end_to_end(self) -> None:
        port = find_free_port()
        about_ws = f"ws://127.0.0.1:{port}/devtools/page/ABOUT"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[
                [
                    {
                        "type": "page",
                        "url": "https://example.net",
                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/OTHER",
                    },
                    {
                        "type": "page",
                        "url": "about:blank",
                        "webSocketDebuggerUrl": about_ws,
                    },
                ]
            ],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, about_ws)

    def test_wait_for_cdp_url_handles_non_page_then_page(self) -> None:
        port = find_free_port()
        page_ws = f"ws://127.0.0.1:{port}/devtools/page/NEXT"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[
                [
                    {"type": "service_worker", "id": "SW"},
                    {"type": "shared_worker", "id": "SH"},
                    {"type": "page", "url": "about:blank", "webSocketDebuggerUrl": page_ws},
                ]
            ],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, page_ws)

    def test_wait_for_cdp_url_handles_http_error_then_list(self) -> None:
        port = find_free_port()
        page_ws = f"ws://127.0.0.1:{port}/devtools/page/RECOVER"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[
                [{"type": "page", "url": "about:blank", "webSocketDebuggerUrl": page_ws}]
            ],
            list_statuses=[500, 200],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=1.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, page_ws)

    def test_wait_for_cdp_url_ignores_browser_targets(self) -> None:
        port = find_free_port()
        page_ws = f"ws://127.0.0.1:{port}/devtools/page/JKL"
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[
                [
                    {
                        "type": "page",
                        "url": "about:blank",
                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/IGNORE",
                    }
                ],
                [{"type": "page", "url": "about:blank", "webSocketDebuggerUrl": page_ws}],
            ],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            ws_url = _wait_for_cdp_url(_DummyProc(), port, timeout_s=1.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)
        self.assertEqual(ws_url, page_ws)

    def test_wait_for_cdp_url_bails_when_process_exits(self) -> None:
        port = find_free_port()

        class ExitingProc:
            def poll(self) -> int:
                return 1

        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[[{"type": "page", "url": "about:blank", "id": "NEVER"}]],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            with self.assertRaises(RuntimeError):
                _wait_for_cdp_url(ExitingProc(), port, timeout_s=0.5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)

    def test_wait_for_cdp_url_times_out_without_pages(self) -> None:
        port = find_free_port()
        state = _CdpState(
            version_payload={
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/XYZ"
            },
            list_payloads=[[{"type": "service_worker"}]],
        )
        server, thread = _start_cdp_server(state, port)
        try:
            with self.assertRaises(RuntimeError):
                _wait_for_cdp_url(_DummyProc(), port, timeout_s=0.3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=0.5)


if __name__ == "__main__":
    unittest.main()
