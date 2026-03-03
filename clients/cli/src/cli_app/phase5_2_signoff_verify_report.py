from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

from cli_app.phase5_2_signoff_verify import (
    iter_required_file_presence,
    scan_redaction_violations,
    validate_manifest,
    validate_sha256,
)
from cli_app.redact import redact_text
from cli_app.signoff_bundle_io import safe_extract_tgz, write_sha256_manifest
from cli_app.signoff_html import render_signoff_verify

PHASE5_2_SIGNOFF_VERIFY_REPORT_V1 = "PHASE5_2_SIGNOFF_VERIFY_REPORT_V1"


def _build_report(*, root: Path, target_type: str, target_name: str) -> tuple[int, dict, list[str]]:
    required_files = [{"relpath": rel, "present": present} for rel, present in iter_required_file_presence(root)]
    missing_required = [entry["relpath"] for entry in required_files if not entry["present"]]

    manifest_ok, manifest_problems = validate_manifest(root)
    sha_ok, sha_problems, file_count = validate_sha256(root)
    redaction_ok, violations, scanned_count = scan_redaction_violations(root)

    overall_ok = (not missing_required) and manifest_ok and sha_ok and redaction_ok
    exit_code = 0 if overall_ok else 1

    report = {
        "verify_version": PHASE5_2_SIGNOFF_VERIFY_REPORT_V1,
        "target_type": target_type,
        "target_name": target_name,
        "created_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "required_files": required_files,
        "manifest_checks": {"ok": manifest_ok and not missing_required, "problems": list(manifest_problems)},
        "sha256_checks": {"ok": sha_ok and not missing_required, "problems": list(sha_problems), "file_count": file_count},
        "redaction_scan": {
            "ok": redaction_ok,
            "violations": sorted(violations, key=lambda item: (str(item.get("file", "")), str(item.get("token", "")))),
            "scanned_count": scanned_count,
        },
        "overall_ok": overall_ok,
        "exit_code": exit_code,
    }
    for relpath in missing_required:
        report["manifest_checks"]["problems"].append(f"missing_file={relpath}")

    summary_lines = [
        "PHASE5_2_SIGNOFF_VERIFY_REPORT_BEGIN",
        PHASE5_2_SIGNOFF_VERIFY_REPORT_V1,
        f"target_type={target_type}",
        f"target_name={target_name}",
        f"required_missing_count={len(missing_required)}",
        f"manifest_ok={str(report['manifest_checks']['ok']).lower()}",
        f"sha256_ok={str(report['sha256_checks']['ok']).lower()}",
        f"redaction_ok={str(redaction_ok).lower()}",
        f"overall_ok={str(overall_ok).lower()}",
        f"exit_code={exit_code}",
    ]
    for relpath in missing_required:
        summary_lines.append(f"required_missing={relpath}")
    for problem in report["manifest_checks"]["problems"]:
        summary_lines.append(f"manifest_problem={problem}")
    for problem in report["sha256_checks"]["problems"]:
        summary_lines.append(f"sha256_problem={problem}")
    for violation in report["redaction_scan"]["violations"]:
        summary_lines.append(f"redaction_violation file={violation['file']} token={violation['token']}")
    if overall_ok:
        summary_lines.append("PHASE5_2_SIGNOFF_VERIFY_REPORT_OK")
    summary_lines.append("PHASE5_2_SIGNOFF_VERIFY_REPORT_END")

    return exit_code, report, summary_lines


def build_verify_report_for_dir(root: Path) -> tuple[int, dict, list[str]]:
    resolved = root.resolve()
    return _build_report(root=resolved, target_type="dir", target_name=resolved.name)


def build_verify_report_for_archive(archive: Path) -> tuple[int, dict, list[str]]:
    resolved = archive.resolve()
    with tempfile.TemporaryDirectory(prefix="phase5_2_signoff_verify_report_") as temp_dir:
        bundle_root = safe_extract_tgz(resolved, temp_root=Path(temp_dir))
        return _build_report(root=bundle_root, target_type="archive", target_name=resolved.name)


def write_verify_report_evidence(*, out_dir: Path, repo_root: Path, target_type: str, target_path: Path) -> dict:
    resolved_target = target_path.resolve()
    if target_type == "dir":
        rc, report, summary_lines = build_verify_report_for_dir(resolved_target)
    elif target_type == "archive":
        rc, report, summary_lines = build_verify_report_for_archive(resolved_target)
    else:
        raise ValueError("unsupported_target_type")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "VERIFY_SUMMARY.txt").write_text(
        "\n".join(redact_text(line) for line in summary_lines) + "\n", encoding="utf-8", newline="\n"
    )
    with (out_dir / "VERIFY_MANIFEST.json").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True))
        handle.write("\n")

    del repo_root
    artifact_links = [
        ("VERIFY_SUMMARY.txt", "VERIFY_SUMMARY.txt"),
        ("VERIFY_MANIFEST.json", "VERIFY_MANIFEST.json"),
        ("sha256.txt", "sha256.txt"),
    ]
    (out_dir / "verify.html").write_text(
        render_signoff_verify(report=report, summary_lines=summary_lines, artifact_links=artifact_links) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_sha256_manifest(out_dir, manifest_name="sha256.txt")
    report["exit_code"] = rc
    return report
