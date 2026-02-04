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


def _fetch_cdp_targets(port: int) -> list[dict]:
    last_error: Optional[Exception] = None
    for path in ("json/list", "json"):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/{path}", timeout=0.5
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if isinstance(payload, list):
                    return payload
        except Exception as exc:  # noqa: BLE001 - preflight polling
            last_error = exc
    if last_error is None:
        raise RuntimeError("chromium remote debugging returned no targets")
    raise last_error


def _select_cdp_page_target(targets: list[dict], port: int) -> Optional[str]:
    candidate: Optional[str] = None
    for target in targets:
        if target.get("type") != "page":
            continue
        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url and target.get("id"):
            ws_url = f"ws://127.0.0.1:{port}/devtools/page/{target['id']}"
        if not ws_url:
            continue
        if "/devtools/browser/" in ws_url:
            continue
        if target.get("url") == "about:blank":
            return ws_url
        candidate = candidate or ws_url
    return candidate


def _wait_for_cdp_url(proc: subprocess.Popen[str], port: int, timeout_s: float) -> str:
    deadline = time.time() + timeout_s
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("chromium exited before remote debugging was ready")
        try:
            targets = _fetch_cdp_targets(port)
            ws_url = _select_cdp_page_target(targets, port)
            if ws_url:
                return ws_url
        except Exception as exc:  # noqa: BLE001 - preflight polling
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for chromium remote debugging: {last_error}")


def launch_chromium(
    chromium_bin: str,
    *,
    cdp_port: int,
    profile_dir: str,
    extra_args: Optional[list[str]] = None,
) -> subprocess.Popen[str]:
    args = [
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
    ]
    if extra_args:
        args.extend(extra_args)
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )


def start_chromium_cdp(
    chromium_bin: str,
    *,
    cdp_port: int,
    profile_dir: str,
    timeout_s: float = 2.5,
    extra_args: Optional[list[str]] = None,
) -> tuple[subprocess.Popen[str], str]:
    proc = launch_chromium(
        chromium_bin,
        cdp_port=cdp_port,
        profile_dir=profile_dir,
        extra_args=extra_args,
    )
    try:
        ws_url = _wait_for_cdp_url(proc, cdp_port, timeout_s)
    except Exception as exc:  # noqa: BLE001 - convert to SkipTest
        terminate_process_group(proc, label="chromium preflight", timeout_s=0.5)
        raise unittest.SkipTest(
            f"chromium remote debugging unavailable: {exc}"
        ) from exc
    return proc, ws_url


def terminate_process_group(
    proc: subprocess.Popen[str], *, label: str, timeout_s: float = 5.0
) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"{label} failed to terminate") from None
