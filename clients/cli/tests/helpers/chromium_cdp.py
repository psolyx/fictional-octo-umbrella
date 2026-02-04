import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
import unittest
from typing import Optional


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_chromium() -> Optional[str]:
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


def _wait_for_cdp_url(proc: subprocess.Popen[str], port: int, timeout_s: float) -> str:
    deadline = time.time() + timeout_s
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("chromium exited before remote debugging was ready")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=0.5
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                ws_url = payload.get("webSocketDebuggerUrl")
                if ws_url:
                    return ws_url
        except Exception as exc:  # noqa: BLE001 - preflight polling
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for chromium remote debugging: {last_error}")


def launch_chromium(
    chromium_bin: str, *, cdp_port: int, profile_dir: str
) -> subprocess.Popen[str]:
    return subprocess.Popen(
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
        start_new_session=True,
    )


def start_chromium_cdp(
    chromium_bin: str, *, cdp_port: int, profile_dir: str, timeout_s: float = 2.5
) -> tuple[subprocess.Popen[str], str]:
    proc = launch_chromium(chromium_bin, cdp_port=cdp_port, profile_dir=profile_dir)
    try:
        ws_url = _wait_for_cdp_url(proc, cdp_port, timeout_s)
    except Exception as exc:  # noqa: BLE001 - convert to SkipTest
        terminate_process_group(proc, label="chromium preflight")
        raise unittest.SkipTest(
            f"chromium remote debugging unavailable: {exc}"
        ) from exc
    return proc, ws_url


def terminate_process_group(proc: subprocess.Popen[str], *, label: str) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"{label} failed to terminate") from None
