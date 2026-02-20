import pathlib
import signal
import socket
import subprocess
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CLIENTS_WEB_ROOT = REPO_ROOT / "clients" / "web"


def pick_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def fetch_url(url, timeout=1.0):
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()
        return response.getcode(), response.headers


def wait_for_url(url, timeout=2.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return fetch_url(url)
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f"Server did not respond for {url}: {last_error}")


def stop_process(proc):
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def start_static_server(root_dir):
    class RootHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root_dir), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), RootHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop_static_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


class TestWebStaticServing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wasm_path = CLIENTS_WEB_ROOT / "vendor" / "mls_harness.wasm"
        cls.created_wasm = False
        if not cls.wasm_path.exists():
            cls.wasm_path.parent.mkdir(parents=True, exist_ok=True)
            cls.wasm_path.write_bytes(b"\x00asm\x01\x00\x00\x00")
            cls.created_wasm = True

    @classmethod
    def tearDownClass(cls):
        if cls.created_wasm and cls.wasm_path.exists():
            cls.wasm_path.unlink()

    def assert_paths_ok(self, base_url, paths):
        for path in paths:
            status, _headers = wait_for_url(f"{base_url}{path}")
            self.assertEqual(status, 200, msg=f"Expected 200 for {path}")

    def test_repo_root_static_server(self):
        server, thread = start_static_server(REPO_ROOT)
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        try:
            self.assert_paths_ok(
                base_url,
                [
                    "/clients/web/index.html",
                    "/clients/web/gateway_ws_client.js",
                    "/clients/web/dm_ui.js",
                    "/clients/web/social_ui.js",
                    "/clients/web/vendor/wasm_exec.js",
                    "/clients/web/vendor/mls_harness.wasm",
                ],
            )
        finally:
            stop_static_server(server, thread)

    def test_clients_web_static_server(self):
        server, thread = start_static_server(CLIENTS_WEB_ROOT)
        port = server.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        try:
            self.assert_paths_ok(
                base_url,
                [
                    "/index.html",
                    "/gateway_ws_client.js",
                    "/dm_ui.js",
                    "/social_ui.js",
                    "/vendor/wasm_exec.js",
                    "/vendor/mls_harness.wasm",
                ],
            )
        finally:
            stop_static_server(server, thread)

    def test_csp_dev_server_headers(self):
        port = pick_free_port()
        proc = subprocess.Popen(
            [
                "python",
                "clients/web/tools/csp_dev_server.py",
                "--serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            status, headers = wait_for_url(f"{base_url}/index.html")
            self.assertEqual(status, 200)

            csp = headers.get("Content-Security-Policy")
            self.assertIsNotNone(csp)
            self.assertIn("connect-src", csp)
            self.assertIn("ws:", csp)
            self.assertIn("wss:", csp)
            self.assertIn("script-src", csp)
            self.assertIn("'wasm-unsafe-eval'", csp)
            self.assertNotIn("'unsafe-eval'", csp)
            self.assertIn("frame-ancestors", csp)
            self.assertIn("'none'", csp)

            self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")

            cache_control = headers.get("Cache-Control")
            self.assertIsNotNone(cache_control)
            self.assertIn("no-store", cache_control)
        finally:
            stop_process(proc)


if __name__ == "__main__":
    unittest.main()
