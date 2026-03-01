from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cli_app.redact import redact_text

PHASE5_2_SIGNOFF_BUNDLE_BEGIN = "PHASE5_2_SIGNOFF_BUNDLE_BEGIN"
PHASE5_2_SIGNOFF_BUNDLE_OK = "PHASE5_2_SIGNOFF_BUNDLE_OK"
PHASE5_2_SIGNOFF_BUNDLE_END = "PHASE5_2_SIGNOFF_BUNDLE_END"
PHASE5_2_SIGNOFF_BUNDLE_V1 = "PHASE5_2_SIGNOFF_BUNDLE_V1"


@dataclass(frozen=True)
class _Step:
    step_id: str
    label: str
    command: list[str]
    output_relpath: str
    extra_env: dict[str, str] | None = None


def _sanitize_tag(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return compact or "unknown"


def _repo_tag(repo_root: Path) -> str:
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return _sanitize_tag(repo_root.name)
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        value = result.stdout.strip()
        if value:
            return _sanitize_tag(value)
    return _sanitize_tag(repo_root.name)


def _platform_tag() -> str:
    return _sanitize_tag(f"{platform.system().lower()}-{platform.machine().lower()}")


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _healthz_ok(base_url: str) -> bool:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/healthz", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return int(response.status) == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def _write_redacted_lines(path: Path, lines: Iterable[str]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            rendered = redact_text(line.rstrip("\n"))
            handle.write(rendered + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _run_subprocess(step: _Step, repo_root: Path, output_path: Path) -> tuple[int, float]:
    env = os.environ.copy()
    if step.extra_env:
        env.update(step.extra_env)
    started = time.monotonic()
    process = subprocess.run(
        step.command,
        cwd=str(repo_root),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    transcript = []
    if process.stdout:
        transcript.extend(process.stdout.splitlines())
    if process.stderr:
        transcript.extend(process.stderr.splitlines())
    _write_redacted_lines(output_path, transcript)
    return int(process.returncode), elapsed


def _start_gateway(repo_root: Path, gateway_log_path: Path) -> tuple[subprocess.Popen[str], str, str]:
    temp_dir = tempfile.mkdtemp(prefix="phase5_2_signoff_gateway_")
    db_path = Path(temp_dir) / "gateway.sqlite3"
    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["PYTHONPATH"] = "gateway/src"
    log_handle = gateway_log_path.open("w", encoding="utf-8", newline="\n")
    process = subprocess.Popen(
        [
            "python",
            "-m",
            "gateway.server",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--db",
            str(db_path),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    ready = False
    attempts = 20
    for attempt in range(1, attempts + 1):
        if _healthz_ok(base_url):
            ready = True
            break
        time.sleep(0.25)
        if process.poll() is not None:
            break
    if not ready:
        with gateway_log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(redact_text(f"gateway_healthz_failed attempts={attempts} base_url={base_url}") + "\n")
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        log_handle.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("gateway_not_running")
    return process, temp_dir, base_url


def _stop_gateway(process: subprocess.Popen[str], temp_dir: str, gateway_log_path: Path) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    shutil.rmtree(temp_dir, ignore_errors=True)
    if gateway_log_path.exists():
        redacted = [redact_text(line.rstrip("\n")) for line in gateway_log_path.read_text(encoding="utf-8").splitlines()]
        _write_redacted_lines(gateway_log_path, redacted)


def _build_steps() -> list[_Step]:
    return [
        _Step(
            "t01",
            "gateway_test_social_profile_and_feed",
            ["env", "PYTHONPATH=gateway/src", "python", "-m", "unittest", "-v", "gateway.tests.test_social_profile_and_feed"],
            "GATE_TESTS/t01_gateway_test_social_profile_and_feed.txt",
        ),
        _Step(
            "t02",
            "gateway_test_retention_gc",
            ["env", "PYTHONPATH=gateway/src", "python", "-m", "unittest", "-v", "gateway.tests.test_retention_gc"],
            "GATE_TESTS/t02_gateway_test_retention_gc.txt",
        ),
        _Step(
            "t03",
            "gateway_test_conversation_list",
            ["env", "PYTHONPATH=gateway/src", "python", "-m", "unittest", "-v", "gateway.tests.test_conversation_list"],
            "GATE_TESTS/t03_gateway_test_conversation_list.txt",
        ),
        _Step(
            "t04",
            "gateway_test_rooms_roles",
            ["env", "PYTHONPATH=gateway/src", "python", "-m", "unittest", "-v", "gateway.tests.test_rooms_roles"],
            "GATE_TESTS/t04_gateway_test_rooms_roles.txt",
        ),
        _Step(
            "t05",
            "gateway_test_presence",
            ["env", "PYTHONPATH=gateway/src", "python", "-m", "unittest", "-v", "gateway.tests.test_presence"],
            "GATE_TESTS/t05_gateway_test_presence.txt",
        ),
        _Step(
            "t06",
            "gateway_test_abuse_controls",
            ["env", "PYTHONPATH=gateway/src", "python", "-m", "unittest", "-v", "gateway.tests.test_abuse_controls"],
            "GATE_TESTS/t06_gateway_test_abuse_controls.txt",
        ),
        _Step(
            "t07",
            "cli_test_web_ui_contracts",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "unittest", "-v", "clients.cli.tests.test_web_ui_contracts"],
            "GATE_TESTS/t07_cli_test_web_ui_contracts.txt",
        ),
        _Step(
            "t08",
            "cli_test_roadmap_spec_contracts",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "unittest", "-v", "clients.cli.tests.test_roadmap_spec_contracts"],
            "GATE_TESTS/t08_cli_test_roadmap_spec_contracts.txt",
        ),
        _Step(
            "t09",
            "tui_social_profile_contracts",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "unittest", "-v", "clients.cli.tests.test_tui_social_profile_contracts"],
            "GATE_TESTS/t09_tui_social_profile_contracts.txt",
        ),
        _Step(
            "t10",
            "tui_account_contracts",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "unittest", "-v", "clients.cli.tests.test_tui_account_contracts"],
            "GATE_TESTS/t10_tui_account_contracts.txt",
        ),
        _Step(
            "t11",
            "tui_rooms_contracts",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "unittest", "-v", "clients.cli.tests.test_tui_rooms_contracts"],
            "GATE_TESTS/t11_tui_rooms_contracts.txt",
        ),
        _Step(
            "t12",
            "phase5_browser_runtime_smoke",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "unittest", "-v", "clients.cli.tests.test_phase5_browser_runtime_smoke"],
            "GATE_TESTS/t12_phase5_browser_runtime_smoke.txt",
        ),
        _Step(
            "t13",
            "phase5_browser_wasm_cli_coexist_smoke",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "unittest", "-v", "clients.cli.tests.test_phase5_browser_wasm_cli_coexist_smoke"],
            "GATE_TESTS/t13_phase5_browser_wasm_cli_coexist_smoke.txt",
        ),
    ]


def run_signoff_bundle(*, repo_root: str, out_evid_root: str, base_url: str | None = None, dry_run: bool = False, out=None):
    out_stream = out if out is not None else os.sys.stdout
    root = Path(repo_root).resolve()
    evid_root = Path(out_evid_root).resolve()
    day = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    utc_stamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = evid_root / f"{day}-{_platform_tag()}-{_repo_tag(root)}" / f"phase5_2_signoff_bundle_{utc_stamp}"

    def emit(line: str) -> None:
        out_stream.write(f"{line}\n")

    emit(PHASE5_2_SIGNOFF_BUNDLE_BEGIN)
    emit(PHASE5_2_SIGNOFF_BUNDLE_V1)

    if dry_run:
        for step in _build_steps():
            emit(f"step={step.step_id} plan {step.label}")
        emit("step=s1 plan phase5_2_smoke_lite_main")
        emit("step=s2 plan phase5_2_static_audit_main")
        emit(PHASE5_2_SIGNOFF_BUNDLE_OK)
        emit(PHASE5_2_SIGNOFF_BUNDLE_END)
        return 0, None

    (bundle_dir / "GATE_TESTS").mkdir(parents=True, exist_ok=True)

    env_lines = [
        f"bundle_version={PHASE5_2_SIGNOFF_BUNDLE_V1}",
        f"repo_root={redact_text(str(root))}",
        f"platform={redact_text(_platform_tag())}",
        f"python={redact_text(os.sys.version.split()[0])}",
        f"utc_started={utc_stamp}",
    ]
    _write_redacted_lines(bundle_dir / "ENV.txt", env_lines)

    manifest: dict[str, object] = {
        "bundle_version": PHASE5_2_SIGNOFF_BUNDLE_V1,
        "created_utc": utc_stamp,
        "steps": [],
        "success": False,
    }
    summary_lines = [PHASE5_2_SIGNOFF_BUNDLE_BEGIN, PHASE5_2_SIGNOFF_BUNDLE_V1]

    all_ok = True
    for step in _build_steps():
        emit(f"step={step.step_id} run {step.label}")
        output_path = bundle_dir / step.output_relpath
        rc, elapsed = _run_subprocess(step, root, output_path)
        status = "PASS" if rc == 0 else "FAIL"
        summary_lines.append(f"step={step.step_id} {status} {step.label} exit_code={rc} duration_s={elapsed:.3f}")
        cast_steps = manifest["steps"]
        assert isinstance(cast_steps, list)
        cast_steps.append(
            {
                "step_id": step.step_id,
                "label": step.label,
                "output": step.output_relpath,
                "exit_code": rc,
                "duration_s": round(elapsed, 3),
                "status": status,
            }
        )
        if rc != 0:
            all_ok = False

    gateway_log = bundle_dir / "GATEWAY_SERVER.txt"
    smoke_rc = 1
    smoke_elapsed = 0.0
    try:
        process, temp_dir, effective_base = _start_gateway(root, gateway_log)
        smoke_step = _Step(
            "s1",
            "phase5_2_smoke_lite_main",
            ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "cli_app.phase5_2_smoke_lite_main"],
            "PHASE5_2_SMOKE_LITE.txt",
            extra_env={"BASE_URL": base_url or effective_base},
        )
        emit("step=s1 run phase5_2_smoke_lite_main")
        smoke_rc, smoke_elapsed = _run_subprocess(smoke_step, root, bundle_dir / smoke_step.output_relpath)
        _stop_gateway(process, temp_dir, gateway_log)
    except Exception as exc:
        _write_redacted_lines(bundle_dir / "PHASE5_2_SMOKE_LITE.txt", [f"step=0 FAIL phase5_2_smoke_lite_main reason={exc}"])
        _write_redacted_lines(gateway_log, [f"gateway_startup_failure reason={exc}"])
        smoke_rc = 1
        smoke_elapsed = 0.0

    smoke_status = "PASS" if smoke_rc == 0 else "FAIL"
    summary_lines.append(f"step=s1 {smoke_status} phase5_2_smoke_lite_main exit_code={smoke_rc} duration_s={smoke_elapsed:.3f}")
    manifest_steps = manifest["steps"]
    assert isinstance(manifest_steps, list)
    manifest_steps.append(
        {
            "step_id": "s1",
            "label": "phase5_2_smoke_lite_main",
            "output": "PHASE5_2_SMOKE_LITE.txt",
            "exit_code": smoke_rc,
            "duration_s": round(smoke_elapsed, 3),
            "status": smoke_status,
        }
    )
    if smoke_rc != 0:
        all_ok = False

    audit_step = _Step(
        "s2",
        "phase5_2_static_audit_main",
        ["env", "PYTHONPATH=clients/cli/src", "python", "-m", "cli_app.phase5_2_static_audit_main"],
        "PHASE5_2_STATIC_AUDIT.txt",
        extra_env={"REPO_ROOT": str(root)},
    )
    emit("step=s2 run phase5_2_static_audit_main")
    audit_rc, audit_elapsed = _run_subprocess(audit_step, root, bundle_dir / audit_step.output_relpath)
    audit_status = "PASS" if audit_rc == 0 else "FAIL"
    summary_lines.append(f"step=s2 {audit_status} phase5_2_static_audit_main exit_code={audit_rc} duration_s={audit_elapsed:.3f}")
    manifest_steps.append(
        {
            "step_id": "s2",
            "label": "phase5_2_static_audit_main",
            "output": "PHASE5_2_STATIC_AUDIT.txt",
            "exit_code": audit_rc,
            "duration_s": round(audit_elapsed, 3),
            "status": audit_status,
        }
    )
    if audit_rc != 0:
        all_ok = False

    if all_ok:
        summary_lines.append(PHASE5_2_SIGNOFF_BUNDLE_OK)
        emit(PHASE5_2_SIGNOFF_BUNDLE_OK)

    summary_lines.append(PHASE5_2_SIGNOFF_BUNDLE_END)
    emit(PHASE5_2_SIGNOFF_BUNDLE_END)

    _write_redacted_lines(bundle_dir / "SIGNOFF_SUMMARY.txt", summary_lines)

    manifest["success"] = all_ok
    manifest["steps"] = manifest_steps
    with (bundle_dir / "MANIFEST.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")

    rel_hashes: list[tuple[str, str]] = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle_dir).as_posix()
        if rel == "sha256.txt":
            continue
        rel_hashes.append((rel, _sha256(path)))
    with (bundle_dir / "sha256.txt").open("w", encoding="utf-8", newline="\n") as handle:
        for rel, digest in rel_hashes:
            handle.write(f"{digest}  {rel}\n")

    return (0 if all_ok else 1), bundle_dir
