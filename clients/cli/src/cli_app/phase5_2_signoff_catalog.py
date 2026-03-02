from __future__ import annotations

import json
import os
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


def _sum_durations(steps: list[dict[str, object]]) -> float:
    total = 0.0
    for step in steps:
        value = step.get("duration_s")
        if isinstance(value, (int, float)):
            total += float(value)
    return total


def _created_key(value: object) -> str:
    return str(value) if isinstance(value, str) else ""


def _safe_relpath(base: Path, target: Path, evidence_root: Path) -> str:
    resolved_target = target.resolve()
    resolved_target.relative_to(evidence_root.resolve())
    return os.path.relpath(resolved_target, base.resolve()).replace("\\", "/")


def scan_signoff_catalog(evidence_root: Path, max_entries: int = 200) -> dict[str, object]:
    bundles: list[dict[str, object]] = []
    compares: list[dict[str, object]] = []
    skipped_incomplete = 0
    skipped_invalid = 0

    directories = sorted([path for path in evidence_root.rglob("*") if path.is_dir()], key=lambda p: p.as_posix())
    for candidate in directories:
        bundle_shape = any((candidate / name).exists() for name in ("MANIFEST.json", "SIGNOFF_SUMMARY.txt", "index.html"))
        compare_shape = any((candidate / name).exists() for name in ("COMPARE_MANIFEST.json", "COMPARE_SUMMARY.txt", "compare.html"))

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
            regression_count = int(manifest.get("regression_count", 0))
            compare_result = str(manifest.get("compare_result", "FAIL"))
            compares.append(
                {
                    "dir_name": candidate.name,
                    "dir_relpath": candidate.relative_to(evidence_root).as_posix(),
                    "created_utc": _created_key(manifest.get("created_utc")),
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

        if bundle_shape or compare_shape:
            skipped_incomplete += 1

    bundles.sort(key=lambda item: str(item["dir_name"]))
    bundles.sort(key=lambda item: str(item["created_utc"]), reverse=True)
    compares.sort(key=lambda item: str(item["dir_name"]))
    compares.sort(key=lambda item: str(item["created_utc"]), reverse=True)

    bundle_overflow = max(0, len(bundles) - max_entries)
    compare_overflow = max(0, len(compares) - max_entries)
    bundles = bundles[:max_entries]
    compares = compares[:max_entries]

    return {
        "catalog_version": PHASE5_2_SIGNOFF_CATALOG_V1,
        "evidence_root_basename": evidence_root.name,
        "entry_limit": max_entries,
        "skipped_incomplete": skipped_incomplete,
        "skipped_invalid": skipped_invalid,
        "truncated_bundles": bundle_overflow,
        "truncated_compares": compare_overflow,
        "bundle_count": len(bundles),
        "compare_count": len(compares),
        "bundles": bundles,
        "compares": compares,
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
    bundle_list = bundles if isinstance(bundles, list) else []
    compare_list = compares if isinstance(compares, list) else []

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

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_lines = [
        f"catalog_version={PHASE5_2_SIGNOFF_CATALOG_V1}",
        f"evidence_root_basename={catalog.get('evidence_root_basename', '')}",
        f"bundle_count={catalog.get('bundle_count', 0)}",
        f"compare_count={catalog.get('compare_count', 0)}",
        f"skipped_incomplete={catalog.get('skipped_incomplete', 0)}",
        f"skipped_invalid={catalog.get('skipped_invalid', 0)}",
        f"truncated_bundles={catalog.get('truncated_bundles', 0)}",
        f"truncated_compares={catalog.get('truncated_compares', 0)}",
    ]
    (out_dir / "CATALOG_SUMMARY.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "CATALOG_MANIFEST.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (out_dir / "catalog.html").write_text(render_signoff_catalog(catalog) + "\n", encoding="utf-8", newline="\n")
    write_sha256_manifest(out_dir)
