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
from cli_app.signoff_bundle_io import parse_sha256_manifest, safe_extract_tgz, sha256_file, verify_sha256_manifest

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


def iter_required_file_presence(root: Path) -> list[tuple[str, bool]]:
    return [(relpath, (root / relpath).is_file()) for relpath in _REQUIRED_FILES]


def validate_manifest(root: Path) -> tuple[bool, list[str]]:
    problems: list[str] = []
    manifest_path = root / "MANIFEST.json"
    summary_path = root / "SIGNOFF_SUMMARY.txt"
    try:
        summary_text = summary_path.read_text(encoding="utf-8")
    except OSError:
        return False, ["summary_missing"]

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, ["manifest_not_json_object"]

    if not isinstance(manifest_data, dict):
        return False, ["manifest_not_object"]

    required_keys = ["bundle_version", "created_utc", "steps", "success"]
    if sorted(manifest_data.keys()) != sorted(required_keys):
        problems.append("manifest_keys_invalid")

    steps = manifest_data.get("steps")
    success = manifest_data.get("success")
    if not isinstance(steps, list):
        problems.append("manifest_steps_not_list")
    if not isinstance(success, bool):
        problems.append("manifest_success_not_bool")

    if isinstance(steps, list):
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                problems.append(f"manifest_step_not_object index={idx}")
                continue
            step_required = ["duration_s", "exit_code", "label", "output", "status", "step_id"]
            if sorted(step.keys()) != step_required:
                problems.append(f"manifest_step_keys_invalid index={idx}")
                continue
            exit_code = step.get("exit_code")
            status = step.get("status")
            if not isinstance(exit_code, int) or not isinstance(status, str):
                problems.append(f"manifest_step_types_invalid index={idx}")
                continue
            expected_status = "PASS" if exit_code == 0 else "FAIL"
            if status != expected_status:
                problems.append(f"manifest_status_mismatch step={step.get('step_id', '')}")

    if PHASE5_2_SIGNOFF_BUNDLE_BEGIN not in summary_text:
        problems.append("summary_missing_begin")
    if PHASE5_2_SIGNOFF_BUNDLE_END not in summary_text:
        problems.append("summary_missing_end")
    summary_has_ok = PHASE5_2_SIGNOFF_BUNDLE_OK in summary_text
    if isinstance(success, bool) and success != summary_has_ok:
        problems.append("summary_ok_mismatch")

    return len(problems) == 0, problems


def validate_sha256(root: Path) -> tuple[bool, list[str], int]:
    problems: list[str] = []
    count = 0
    try:
        entries = parse_sha256_manifest((root / "sha256.txt").read_text(encoding="utf-8"))
        count = len(entries)
        verify_sha256_manifest(root)
        # Digest pass over entries to keep deterministic/portable file_count semantics.
        for relpath, digest in entries:
            if sha256_file(root / relpath) != digest:
                problems.append(f"sha256_mismatch file={relpath}")
                break
    except (OSError, ValueError) as exc:
        problems.append(str(exc))
    return len(problems) == 0, problems, count


def scan_redaction_violations(root: Path) -> tuple[bool, list[dict[str, str]], int]:
    transcript_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".txt", ".json", ".html"}
    )
    violations: list[dict[str, str]] = []
    for relpath in transcript_paths:
        text = (root / relpath).read_text(encoding="utf-8", errors="replace")
        for token, pattern in _REDACTION_FORBIDDEN_PATTERNS:
            if pattern.search(text):
                violations.append({"file": relpath, "token": token})
    return len(violations) == 0, violations, len(transcript_paths)


def verify_signoff_bundle(evid_dir: str, out=None) -> int:
    out_stream = out if out is not None else os.sys.stdout
    root = Path(evid_dir).resolve()

    for rel, present in iter_required_file_presence(root):
        if not present:
            return _fail(out_stream, f"missing_file={rel}")

    manifest_ok, manifest_problems = validate_manifest(root)
    if not manifest_ok:
        return _fail(out_stream, manifest_problems[0])

    sha_ok, sha_problems, _count = validate_sha256(root)
    if not sha_ok:
        return _fail(out_stream, sha_problems[0])

    redaction_ok, violations, _scan_count = scan_redaction_violations(root)
    if not redaction_ok:
        first = violations[0]
        out_stream.write(f"redaction_violation file={first['file']} token={first['token']}\n")
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
