import http.server
import json
import threading
from collections import deque
from pathlib import Path
from typing import Deque, Iterable, Optional


class SmokeServer:
    def __init__(self, root: Path, *, csp_value: str, log_limit: int = 200) -> None:
        self._root = root
        self._csp_value = csp_value
        self._logs: Deque[str] = deque(maxlen=log_limit)
        self._lock = threading.Lock()
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None:
            return
        handler = self._make_handler()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        self._thread = thread

    def shutdown(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("server not started")
        return self._server.server_address[1]

    def snapshot_logs(self) -> list[str]:
        with self._lock:
            return list(self._logs)

    def _append_logs(self, entries: Iterable[str]) -> None:
        with self._lock:
            for entry in entries:
                self._logs.append(entry)

    def _make_handler(self):
        root = self._root
        csp_value = self._csp_value
        append_logs = self._append_logs
        logs_snapshot = self.snapshot_logs

        class SmokeHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, directory=str(root), **kwargs)

            def log_message(self, format: str, *args) -> None:  # noqa: A003 - match base signature
                return

            def end_headers(self) -> None:
                self.send_header("Content-Security-Policy", csp_value)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def guess_type(self, path: str) -> str:
                if path.endswith(".wasm"):
                    return "application/wasm"
                return super().guess_type(path)

            def do_GET(self) -> None:
                if self.path == "/__log":
                    payload = json.dumps({"entries": list(logs_snapshot())})
                    encoded = payload.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                super().do_GET()

            def do_POST(self) -> None:
                if self.path != "/__log":
                    self.send_error(404, "Not Found")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                entries: list[str] = []
                if raw:
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        entries.append(raw.decode("utf-8", errors="replace"))
                    else:
                        if isinstance(payload, dict) and isinstance(payload.get("entries"), list):
                            entries.extend(str(item) for item in payload["entries"])
                        elif isinstance(payload, dict) and "entry" in payload:
                            entries.append(str(payload["entry"]))
                        else:
                            entries.append(json.dumps(payload, sort_keys=True))
                if entries:
                    append_logs(entries)
                self.send_response(204)
                self.end_headers()

        return SmokeHandler
