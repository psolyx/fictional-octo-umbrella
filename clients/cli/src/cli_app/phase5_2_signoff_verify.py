from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import TextIO

from cli_app.phase5_2_signoff_bundle import (
    PHASE5_2_SIGNOFF_BUNDLE_BEGIN,
    PHASE5_2_SIGNOFF_BUNDLE_END,
    PHASE5_2_SIGNOFF_BUNDLE_OK,
)
from cli_app.signoff_bundle_io import safe_extract_tgz, verify_sha256_manifest

PHASE5_2_SIGNOFF_VERIFY_BEGIN = "PHASE5_2_SIGNOFF_VERIFY_BEGIN"
PHASE5_2_SIGNOFF_VERIFY_OK = "PHASE5_2_SIGNOFF_VERIFY_OK"
PHASE5_2_SIGNOFF_VERIFY_END = "PHASE5_2_SIGNOFF_VERIFY_END"
PHASE5_2_SIGNOFF_VERIFY_V1 = "PHASE5_2_SIGNOFF_VERIFY_V1"

_REQUIRED_FILES = [
    "ENV.txt",
    "GATEWAY_SERVER.txt",
    "GATE_TESTS/t01_gateway_test_social_profile_and_feed.txt",
    "GATE_TESTS/t02_gateway_test_retention_gc.txt",
    "GATE_TESTS/t03_gateway_test_conversation_list.txt",
    "GATE_TESTS/t04_gateway_test_rooms_roles.txt",
    "GATE_TESTS/t05_gateway_test_presence.txt",
    "GATE_TESTS/t06_gateway_test_abuse_controls.txt",
    "GATE_TESTS/t07_cli_test_web_ui_contracts.txt",
    "GATE_TESTS/t08_cli_test_roadmap_spec_contracts.txt",
    "GATE_TESTS/t09_tui_social_profile_contracts.txt",
    "GATE_TESTS/t10_tui_account_contracts.txt",
    "GATE_TESTS/t11_tui_rooms_contracts.txt",
    "GATE_TESTS/t12_phase5_browser_runtime_smoke.txt",
    "GATE_TESTS/t13_phase5_browser_wasm_cli_coexist_smoke.txt",
    "MANIFEST.json",
    "PHASE5_2_SMOKE_LITE.txt",
    "PHASE5_2_STATIC_AUDIT.txt",
    "SIGNOFF_SUMMARY.txt",
    "index.html",
    "sha256.txt",
]

_REDACTION_FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("BEGIN PRIVATE KEY", re.compile(r"BEGIN PRIVATE KEY")),
    (
        "Bearer ",
        re.compile(r"Bearer\s+(?!\[REDACTED\])[^\s]+", flags=re.IGNORECASE),
    ),
    (
        "auth_token",
        re.compile(
            r"(?:auth_token|bootstrap_token|device_credential|session_token|resume_token|token|credential)"
            r"\s*[:=]\s*[\"']?(?!\[REDACTED\])[A-Za-z0-9._\-/+=~]+",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "resume_token",
        re.compile(
            r"[?&](?:auth_token|resume_token|token|credential)=(?!\[REDACTED\])[^&#\s]+",
            flags=re.IGNORECASE,
        ),
    ),
]



def _fail(out: TextIO, message: str) -> int:
    out.write(f"verify_fail {message}\n")
    return 1


def verify_signoff_bundle(evid_dir: str, out=None) -> int:
    out_stream = out if out is not None else os.sys.stdout
    root = Path(evid_dir).resolve()

    for rel in _REQUIRED_FILES:
        if not (root / rel).is_file():
            return _fail(out_stream, f"missing_file={rel}")

    summary_text = (root / "SIGNOFF_SUMMARY.txt").read_text(encoding="utf-8")
    manifest_data = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if not isinstance(manifest_data, dict):
        return _fail(out_stream, "manifest_not_object")

    required_keys = ["bundle_version", "created_utc", "steps", "success"]
    if sorted(manifest_data.keys()) != sorted(required_keys):
        return _fail(out_stream, "manifest_keys_invalid")
    if not isinstance(manifest_data["steps"], list):
        return _fail(out_stream, "manifest_steps_not_list")
    if not isinstance(manifest_data["success"], bool):
        return _fail(out_stream, "manifest_success_not_bool")

    for idx, step in enumerate(manifest_data["steps"]):
        if not isinstance(step, dict):
            return _fail(out_stream, f"manifest_step_not_object index={idx}")
        step_required = ["duration_s", "exit_code", "label", "output", "status", "step_id"]
        if sorted(step.keys()) != step_required:
            return _fail(out_stream, f"manifest_step_keys_invalid index={idx}")
        exit_code = step["exit_code"]
        status = step["status"]
        if not isinstance(exit_code, int) or not isinstance(status, str):
            return _fail(out_stream, f"manifest_step_types_invalid index={idx}")
        expected_status = "PASS" if exit_code == 0 else "FAIL"
        if status != expected_status:
            return _fail(out_stream, f"manifest_status_mismatch step={step['step_id']}")

    if PHASE5_2_SIGNOFF_BUNDLE_BEGIN not in summary_text:
        return _fail(out_stream, "summary_missing_begin")
    if PHASE5_2_SIGNOFF_BUNDLE_END not in summary_text:
        return _fail(out_stream, "summary_missing_end")
    summary_has_ok = PHASE5_2_SIGNOFF_BUNDLE_OK in summary_text
    if bool(manifest_data["success"]) != summary_has_ok:
        return _fail(out_stream, "summary_ok_mismatch")

    try:
        verify_sha256_manifest(root)
    except ValueError as exc:
        return _fail(out_stream, str(exc))

    transcript_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".txt", ".json", ".html"}
    )
    for relpath in transcript_paths:
        text = (root / relpath).read_text(encoding="utf-8", errors="replace")
        for token, pattern in _REDACTION_FORBIDDEN_PATTERNS:
            if pattern.search(text):
                out_stream.write(f"redaction_violation file={relpath} token={token}\n")
                return 1

    out_stream.write(f"{PHASE5_2_SIGNOFF_VERIFY_OK}\n")
    return 0



def verify_signoff_archive(archive_path: str, out=None) -> int:
    out_stream = out if out is not None else os.sys.stdout
    archive = Path(archive_path).resolve()

    with tempfile.TemporaryDirectory(prefix="phase5_2_signoff_verify_") as temp_dir:
        extract_root = Path(temp_dir)
        try:
            bundle_root = safe_extract_tgz(archive, temp_root=extract_root)
        except ValueError as exc:
            return _fail(out_stream, str(exc))

        return verify_signoff_bundle(str(bundle_root), out=out_stream)
