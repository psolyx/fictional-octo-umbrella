from __future__ import annotations

import json
import os
import re
from pathlib import Path

from cli_app.signoff_bundle_io import write_sha256_manifest
from cli_app.signoff_html import render_signoff_catalog

PHASE5_2_SIGNOFF_CATALOG_BEGIN = "PHASE5_2_SIGNOFF_CATALOG_BEGIN"
PHASE5_2_SIGNOFF_CATALOG_OK = "PHASE5_2_SIGNOFF_CATALOG_OK"
PHASE5_2_SIGNOFF_CATALOG_END = "PHASE5_2_SIGNOFF_CATALOG_END"
PHASE5_2_SIGNOFF_CATALOG_V1 = "PHASE5_2_SIGNOFF_CATALOG_V1"


def _is_bundle_dir(path: Path) -> bool:
    required = ("MANIFEST.json", "SIGNOFF_SUMMARY.txt", "sha256.txt", "index.html")
    return all((path / name).is_file() for name in required)


def _is_compare_dir(path: Path) -> bool:
    required = ("COMPARE_MANIFEST.json", "COMPARE_SUMMARY.txt", "sha256.txt", "compare.html")
    return all((path / name).is_file() for name in required)


def _is_autopilot_dir(path: Path) -> bool:
    required = ("AUTOPILOT_MANIFEST.json", "AUTOPILOT_SUMMARY.txt", "sha256.txt", "autopilot.html")
    return all((path / name).is_file() for name in required)


def _is_verify_report_dir(path: Path) -> bool:
    required = ("VERIFY_MANIFEST.json", "VERIFY_SUMMARY.txt", "sha256.txt", "verify.html")
    return all((path / name).is_file() for name in required)


def _sum_durations(steps: list[dict[str, object]]) -> float:
    total = 0.0
    for step in steps:
        value = step.get("duration_s")
        if isinstance(value, (int, float)):
            total += float(value)
    return total


def _created_key(value: object) -> str:
    return str(value) if isinstance(value, str) else ""


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compare_created_fallback(created_utc: str, dir_name: str) -> str:
    if created_utc:
        return created_utc
    match = re.search(r"(\d{8}T\d{6}Z)", dir_name)
    if not match:
        return ""
    stamp = match.group(1)
    return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"


def _safe_relpath(base: Path, target: Path, evidence_root: Path) -> str:
    resolved_target = target.resolve()
    resolved_target.relative_to(evidence_root.resolve())
    return os.path.relpath(resolved_target, base.resolve()).replace("\\", "/")


def scan_signoff_catalog(evidence_root: Path, max_entries: int = 200) -> dict[str, object]:
    bundles: list[dict[str, object]] = []
    compares: list[dict[str, object]] = []
    autopilots: list[dict[str, object]] = []
    verify_reports: list[dict[str, object]] = []
    skipped_incomplete = 0
    skipped_invalid = 0

    directories = sorted([path for path in evidence_root.rglob("*") if path.is_dir()], key=lambda p: p.as_posix())
    for candidate in directories:
        bundle_shape = any((candidate / name).exists() for name in ("MANIFEST.json", "SIGNOFF_SUMMARY.txt", "index.html"))
        compare_shape = any((candidate / name).exists() for name in ("COMPARE_MANIFEST.json", "COMPARE_SUMMARY.txt", "compare.html"))
        autopilot_shape = any((candidate / name).exists() for name in ("AUTOPILOT_MANIFEST.json", "AUTOPILOT_SUMMARY.txt", "autopilot.html"))
        verify_shape = any((candidate / name).exists() for name in ("VERIFY_MANIFEST.json", "VERIFY_SUMMARY.txt", "verify.html"))

        if _is_bundle_dir(candidate):
            try:
                manifest = json.loads((candidate / "MANIFEST.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                skipped_invalid += 1
                continue
            steps_raw = manifest.get("steps")
            steps: list[dict[str, object]] = [step for step in steps_raw if isinstance(step, dict)] if isinstance(steps_raw, list) else []
            failure_steps = sorted(
                [str(step.get("step_id", "")) for step in steps if str(step.get("status", "")) != "PASS"]
            )
            parent = candidate.parent
            archive = parent / f"{candidate.name}.tgz"
            archive_sha = parent / f"{candidate.name}.tgz.sha256"
            bundles.append(
                {
                    "dir_name": candidate.name,
                    "dir_relpath": candidate.relative_to(evidence_root).as_posix(),
                    "created_utc": _created_key(manifest.get("created_utc")),
                    "result": "PASS" if bool(manifest.get("success")) else "FAIL",
                    "total_duration_s": round(_sum_durations(steps), 3),
                    "regression_risk": failure_steps,
                    "index_html": "index.html",
                    "manifest_json": "MANIFEST.json",
                    "sha256_txt": "sha256.txt",
                    "archive_available": archive.is_file(),
                    "archive_sha_available": archive_sha.is_file(),
                }
            )
            continue

        if _is_compare_dir(candidate):
            try:
                manifest = json.loads((candidate / "COMPARE_MANIFEST.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                skipped_invalid += 1
                continue
            regression_count = _int_value(manifest.get("regression_count", 0), 0)
            compare_result = str(manifest.get("compare_result", "FAIL"))
            created_utc = _compare_created_fallback(_created_key(manifest.get("created_utc")), candidate.name)
            compares.append(
                {
                    "dir_name": candidate.name,
                    "dir_relpath": candidate.relative_to(evidence_root).as_posix(),
                    "created_utc": created_utc,
                    "result": "PASS" if compare_result == "PASS" and regression_count == 0 else "FAIL",
                    "regression_count": regression_count,
                    "compare_html": "compare.html",
                    "manifest_json": "COMPARE_MANIFEST.json",
                    "sha256_txt": "sha256.txt",
                    "bundle_a_name": str(manifest.get("bundle_a_name", "")),
                    "bundle_b_name": str(manifest.get("bundle_b_name", "")),
                }
            )
            continue

        if _is_autopilot_dir(candidate):
            try:
                manifest = json.loads((candidate / "AUTOPILOT_MANIFEST.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                skipped_invalid += 1
                continue
            created_utc = _compare_created_fallback(_created_key(manifest.get("created_utc")), candidate.name)
            autopilots.append(
                {
                    "dir_name": candidate.name,
                    "dir_relpath": candidate.relative_to(evidence_root).as_posix(),
                    "created_utc": created_utc,
                    "success": bool(manifest.get("success")),
                    "exit_code": _int_value(manifest.get("exit_code", 1), 1),
                    "bundle_dir_name": str(manifest.get("bundle_dir_name", "")),
                    "baseline_bundle_dir_name": str(manifest.get("baseline_bundle_dir_name", "")),
                    "compare_result": str(manifest.get("compare_result", "")),
                    "regression_count": _int_value(manifest.get("regression_count", 0), 0),
                    "verify_overall_ok": bool(manifest.get("verify_overall_ok")),
                    "verify_exit_code": _int_value(manifest.get("verify_exit_code", 1), 1),
                    "verify_report_dir": str(manifest.get("verify_report_dir", "")),
                    "verify_html_rel": str(manifest.get("verify_html_rel", "")),
                    "signoff_txt_name": str(manifest.get("signoff_txt_name", "")),
                    "autopilot_html": "autopilot.html",
                    "manifest_json": "AUTOPILOT_MANIFEST.json",
                    "sha256_txt": "sha256.txt",
                    "result": "PASS" if bool(manifest.get("success")) else "FAIL",
                }
            )
            continue

        if _is_verify_report_dir(candidate):
            try:
                manifest = json.loads((candidate / "VERIFY_MANIFEST.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                skipped_invalid += 1
                continue
            verify_reports.append(
                {
                    "dir_name": candidate.name,
                    "dir_relpath": candidate.relative_to(evidence_root).as_posix(),
                    "created_utc": _created_key(manifest.get("created_utc")),
                    "overall_ok": bool(manifest.get("overall_ok")),
                    "exit_code": _int_value(manifest.get("exit_code", 1), 1),
                    "target_type": str(manifest.get("target_type", "")),
                    "target_name": str(manifest.get("target_name", "")),
                    "verify_html": "verify.html",
                    "manifest_json": "VERIFY_MANIFEST.json",
                    "sha256_txt": "sha256.txt",
                    "result": "PASS" if bool(manifest.get("overall_ok")) else "FAIL",
                }
            )
            continue

        if bundle_shape or compare_shape or autopilot_shape or verify_shape:
            skipped_incomplete += 1

    bundles.sort(key=lambda item: str(item["dir_name"]))
    bundles.sort(key=lambda item: str(item["created_utc"]), reverse=True)
    compares.sort(key=lambda item: str(item["dir_name"]))
    compares.sort(key=lambda item: str(item["created_utc"]), reverse=True)
    autopilots.sort(key=lambda item: str(item["dir_name"]))
    autopilots.sort(key=lambda item: str(item["created_utc"]), reverse=True)
    verify_reports.sort(key=lambda item: str(item["dir_name"]))
    verify_reports.sort(key=lambda item: str(item["created_utc"]), reverse=True)

    bundle_overflow = max(0, len(bundles) - max_entries)
    compare_overflow = max(0, len(compares) - max_entries)
    autopilot_overflow = max(0, len(autopilots) - max_entries)
    verify_report_overflow = max(0, len(verify_reports) - max_entries)
    bundles = bundles[:max_entries]
    compares = compares[:max_entries]
    autopilots = autopilots[:max_entries]
    verify_reports = verify_reports[:max_entries]

    return {
        "catalog_version": PHASE5_2_SIGNOFF_CATALOG_V1,
        "evidence_root_basename": evidence_root.name,
        "entry_limit": max_entries,
        "skipped_incomplete": skipped_incomplete,
        "skipped_invalid": skipped_invalid,
        "truncated_bundles": bundle_overflow,
        "truncated_compares": compare_overflow,
        "truncated_autopilots": autopilot_overflow,
        "truncated_verify_reports": verify_report_overflow,
        "bundle_count": len(bundles),
        "compare_count": len(compares),
        "autopilot_count": len(autopilots),
        "verify_report_count": len(verify_reports),
        "bundles": bundles,
        "compares": compares,
        "autopilots": autopilots,
        "verify_reports": verify_reports,
    }


def discover_signoff_bundle_entries(evidence_root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    directories = sorted([path for path in evidence_root.rglob("*") if path.is_dir()], key=lambda p: p.as_posix())
    for candidate in directories:
        if not _is_bundle_dir(candidate):
            continue
        try:
            manifest = json.loads((candidate / "MANIFEST.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        parent = candidate.parent
        archive = parent / f"{candidate.name}.tgz"
        entries.append(
            {
                "bundle_dir": candidate,
                "bundle_dir_name": candidate.name,
                "created_utc": _created_key(manifest.get("created_utc")),
                "success": bool(manifest.get("success")),
                "archive_path": archive if archive.is_file() else None,
            }
        )
    return entries


def write_signoff_catalog_outputs(catalog: dict[str, object], *, evidence_root: Path, out_dir: Path) -> None:
    bundles = catalog.get("bundles")
    compares = catalog.get("compares")
    autopilots = catalog.get("autopilots")
    verify_reports = catalog.get("verify_reports")
    bundle_list = bundles if isinstance(bundles, list) else []
    compare_list = compares if isinstance(compares, list) else []
    autopilot_list = autopilots if isinstance(autopilots, list) else []
    verify_report_list = verify_reports if isinstance(verify_reports, list) else []

    for entry in bundle_list:
        if not isinstance(entry, dict):
            continue
        run_dir = evidence_root / str(entry.get("dir_relpath", ""))
        entry["run_relpath_from_catalog"] = _safe_relpath(out_dir, run_dir, evidence_root)
        entry["index_href"] = _safe_relpath(out_dir, run_dir / "index.html", evidence_root)
        entry["manifest_href"] = _safe_relpath(out_dir, run_dir / "MANIFEST.json", evidence_root)
        entry["sha256_href"] = _safe_relpath(out_dir, run_dir / "sha256.txt", evidence_root)
        archive = run_dir.parent / f"{run_dir.name}.tgz"
        archive_sha = run_dir.parent / f"{run_dir.name}.tgz.sha256"
        if archive.is_file() and archive_sha.is_file():
            entry["archive_href"] = _safe_relpath(out_dir, archive, evidence_root)
            entry["archive_sha_href"] = _safe_relpath(out_dir, archive_sha, evidence_root)

    for entry in compare_list:
        if not isinstance(entry, dict):
            continue
        run_dir = evidence_root / str(entry.get("dir_relpath", ""))
        entry["run_relpath_from_catalog"] = _safe_relpath(out_dir, run_dir, evidence_root)
        entry["compare_href"] = _safe_relpath(out_dir, run_dir / "compare.html", evidence_root)
        entry["manifest_href"] = _safe_relpath(out_dir, run_dir / "COMPARE_MANIFEST.json", evidence_root)
        entry["sha256_href"] = _safe_relpath(out_dir, run_dir / "sha256.txt", evidence_root)

    for entry in autopilot_list:
        if not isinstance(entry, dict):
            continue
        run_dir = evidence_root / str(entry.get("dir_relpath", ""))
        entry["run_relpath_from_catalog"] = _safe_relpath(out_dir, run_dir, evidence_root)
        entry["autopilot_href"] = _safe_relpath(out_dir, run_dir / "autopilot.html", evidence_root)
        entry["autopilot_manifest_href"] = _safe_relpath(out_dir, run_dir / "AUTOPILOT_MANIFEST.json", evidence_root)
        entry["autopilot_sha256_href"] = _safe_relpath(out_dir, run_dir / "sha256.txt", evidence_root)
        signoff_txt_name = str(entry.get("signoff_txt_name", ""))
        if signoff_txt_name:
            signoff_txt_path = run_dir / signoff_txt_name
            if signoff_txt_path.is_file():
                entry["signoff_txt_href"] = _safe_relpath(out_dir, signoff_txt_path, evidence_root)
        verify_html_rel = str(entry.get("verify_html_rel", ""))
        if verify_html_rel:
            verify_target = run_dir / verify_html_rel
            if verify_target.is_file():
                entry["verify_href"] = _safe_relpath(out_dir, verify_target, evidence_root)
        if not entry.get("verify_href"):
            probed_verify = run_dir / "VERIFY" / "verify.html"
            if probed_verify.is_file():
                entry["verify_href"] = _safe_relpath(out_dir, probed_verify, evidence_root)
        probed_compare = run_dir / "COMPARE" / "compare.html"
        if probed_compare.is_file():
            entry["compare_href"] = _safe_relpath(out_dir, probed_compare, evidence_root)

    for entry in verify_report_list:
        if not isinstance(entry, dict):
            continue
        run_dir = evidence_root / str(entry.get("dir_relpath", ""))
        entry["run_relpath_from_catalog"] = _safe_relpath(out_dir, run_dir, evidence_root)
        entry["verify_href"] = _safe_relpath(out_dir, run_dir / "verify.html", evidence_root)
        entry["verify_manifest_href"] = _safe_relpath(out_dir, run_dir / "VERIFY_MANIFEST.json", evidence_root)
        entry["verify_sha256_href"] = _safe_relpath(out_dir, run_dir / "sha256.txt", evidence_root)

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_lines = [
        f"catalog_version={PHASE5_2_SIGNOFF_CATALOG_V1}",
        f"evidence_root_basename={catalog.get('evidence_root_basename', '')}",
        f"bundle_count={catalog.get('bundle_count', 0)}",
        f"compare_count={catalog.get('compare_count', 0)}",
        f"autopilot_count={catalog.get('autopilot_count', 0)}",
        f"verify_report_count={catalog.get('verify_report_count', 0)}",
        f"skipped_incomplete={catalog.get('skipped_incomplete', 0)}",
        f"skipped_invalid={catalog.get('skipped_invalid', 0)}",
        f"truncated_bundles={catalog.get('truncated_bundles', 0)}",
        f"truncated_compares={catalog.get('truncated_compares', 0)}",
        f"truncated_autopilots={catalog.get('truncated_autopilots', 0)}",
        f"truncated_verify_reports={catalog.get('truncated_verify_reports', 0)}",
    ]
    (out_dir / "CATALOG_SUMMARY.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "CATALOG_MANIFEST.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (out_dir / "catalog.html").write_text(render_signoff_catalog(catalog) + "\n", encoding="utf-8", newline="\n")
    write_sha256_manifest(out_dir)
