from __future__ import annotations

import datetime as dt
import io
import json
import os
import platform
import sys
from pathlib import Path
from typing import IO

from cli_app.phase5_2_signoff_bundle import run_signoff_bundle
from cli_app.phase5_2_signoff_catalog import discover_signoff_bundle_entries
from cli_app.phase5_2_signoff_compare import compare_signoff_bundles
from cli_app.phase5_2_signoff_verify import verify_signoff_archive, verify_signoff_bundle
from cli_app.signoff_bundle_io import write_sha256_manifest
from cli_app.signoff_html import render_signoff_autopilot
from cli_app.redact import redact_text

PHASE5_2_SIGNOFF_AUTOPILOT_BEGIN = "PHASE5_2_SIGNOFF_AUTOPILOT_BEGIN"
PHASE5_2_SIGNOFF_AUTOPILOT_OK = "PHASE5_2_SIGNOFF_AUTOPILOT_OK"
PHASE5_2_SIGNOFF_AUTOPILOT_END = "PHASE5_2_SIGNOFF_AUTOPILOT_END"
PHASE5_2_SIGNOFF_AUTOPILOT_V1 = "PHASE5_2_SIGNOFF_AUTOPILOT_V1"


def _platform_tag() -> str:
    machine = platform.machine().lower() or "unknown"
    system = platform.system().lower() or "unknown"
    return f"{system}-{machine}"


def _rel_href(from_dir: Path, target: Path) -> str:
    return os.path.relpath(target, from_dir).replace("\\", "/")


def _discover_latest_catalog_html(evidence_root: Path) -> Path | None:
    candidates: list[Path] = []
    for path in evidence_root.rglob("catalog.html"):
        if not path.is_file():
            continue
        if not (path.parent / "CATALOG_MANIFEST.json").is_file():
            continue
        candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda value: value.as_posix())
    return candidates[-1]


def run_autopilot(
    repo_root: Path,
    out_evid_root: Path,
    evidence_root: Path,
    base_url: str | None,
    prefer_archive: bool = True,
    compare_prefer_archive: bool = True,
    no_archive: bool = False,
    out: IO[str] = sys.stdout,
) -> dict:
    del out
    if no_archive:
        os.environ["SIGNOFF_NO_ARCHIVE"] = "1"
    else:
        os.environ.pop("SIGNOFF_NO_ARCHIVE", None)

    bundle_rc, bundle_dir = run_signoff_bundle(
        repo_root=str(repo_root),
        out_evid_root=str(out_evid_root),
        base_url=base_url,
        dry_run=False,
        out=io.StringIO(),
    )
    archive_path = bundle_dir.parent / f"{bundle_dir.name}.tgz"
    archive = archive_path if archive_path.is_file() else None

    verify_mode = "archive" if prefer_archive and archive is not None else "dir"
    verify_log = io.StringIO()
    if verify_mode == "archive":
        verify_rc = verify_signoff_archive(str(archive), out=verify_log)
    else:
        verify_rc = verify_signoff_bundle(str(bundle_dir), out=verify_log)

    baseline_entries = discover_signoff_bundle_entries(evidence_root)
    baseline_sorted = sorted(baseline_entries, key=lambda item: str(item.get("bundle_dir_name", "")))
    baseline_sorted.sort(key=lambda item: str(item.get("created_utc", "")), reverse=True)

    baseline = None
    for entry in baseline_sorted:
        entry_dir = entry.get("bundle_dir")
        if not isinstance(entry_dir, Path):
            continue
        if entry_dir.resolve() == bundle_dir.resolve():
            continue
        if bool(entry.get("success")):
            baseline = entry
            break

    day = dt.datetime.utcnow().strftime("%Y-%m-%d")
    utc_stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    autopilot_dir = out_evid_root / f"{day}-{_platform_tag()}-autopilot" / f"phase5_2_signoff_autopilot_{utc_stamp}"
    autopilot_dir.mkdir(parents=True, exist_ok=True)

    compare_mode = "skipped"
    compare_result = "SKIPPED"
    regression_count = 0
    compare_rc = 0
    compare_dir: Path | None = None

    if baseline is not None and verify_rc == 0:
        baseline_dir = baseline.get("bundle_dir")
        baseline_archive = baseline.get("archive_path")
        if isinstance(baseline_dir, Path):
            if (
                compare_prefer_archive
                and isinstance(baseline_archive, Path)
                and baseline_archive.is_file()
                and archive is not None
            ):
                compare_mode = "archive"
                source_a = str(baseline_archive)
                source_b = str(archive)
            else:
                compare_mode = "dir"
                source_a = str(baseline_dir)
                source_b = str(bundle_dir)
            compare_log = io.StringIO()
            compare_dir = autopilot_dir / "COMPARE"
            compare_rc = compare_signoff_bundles(
                mode=compare_mode,
                bundle_a=source_a,
                bundle_b=source_b,
                out_dir=str(compare_dir),
                out=compare_log,
            )
            for line in compare_log.getvalue().splitlines():
                line_clean = redact_text(line.strip())
                if line_clean.startswith("regression_count="):
                    try:
                        regression_count = int(line_clean.split("=", 1)[1])
                    except ValueError:
                        regression_count = 0
            compare_result = "PASS" if compare_rc == 0 else "FAIL"

    success = bundle_rc == 0 and verify_rc == 0 and compare_result != "FAIL"
    if compare_rc == 2 or compare_result == "FAIL":
        exit_code = 2
    elif bundle_rc != 0 or verify_rc != 0 or compare_rc == 1:
        exit_code = 1
    else:
        exit_code = 0

    baseline_name = str(baseline.get("bundle_dir_name")) if isinstance(baseline, dict) else "none"
    archive_name = archive.name if archive is not None else "none"

    summary_lines = [
        PHASE5_2_SIGNOFF_AUTOPILOT_BEGIN,
        f"bundle_dir_name={bundle_dir.name}",
        f"archive_name={archive_name}",
        f"verify_mode={verify_mode}",
        f"baseline_bundle_dir_name={baseline_name}",
        f"compare_mode={compare_mode}",
        f"compare_result={compare_result}",
    ]
    if success:
        summary_lines.append(PHASE5_2_SIGNOFF_AUTOPILOT_OK)
    summary_lines.append(PHASE5_2_SIGNOFF_AUTOPILOT_END)

    manifest = {
        "autopilot_version": PHASE5_2_SIGNOFF_AUTOPILOT_V1,
        "archive_name": archive_name,
        "baseline_bundle_dir_name": baseline_name,
        "bundle_dir_name": bundle_dir.name,
        "compare_mode": compare_mode,
        "compare_result": compare_result,
        "exit_code": exit_code,
        "regression_count": regression_count,
        "success": success,
        "verify_mode": verify_mode,
    }

    summary_path = autopilot_dir / "AUTOPILOT_SUMMARY.txt"
    manifest_path = autopilot_dir / "AUTOPILOT_MANIFEST.json"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    artifact_links: list[tuple[str, str]] = [
        (_rel_href(autopilot_dir, bundle_dir / "index.html"), "new bundle index.html"),
        (_rel_href(autopilot_dir, summary_path), summary_path.name),
        (_rel_href(autopilot_dir, manifest_path), manifest_path.name),
    ]
    if verify_mode == "archive" and archive is not None:
        archive_sha = Path(f"{archive.as_posix()}.sha256")
        artifact_links.append((_rel_href(autopilot_dir, archive), archive.name))
        if archive_sha.is_file():
            artifact_links.append((_rel_href(autopilot_dir, archive_sha), archive_sha.name))
    else:
        artifact_links.append((_rel_href(autopilot_dir, bundle_dir / "sha256.txt"), "new bundle sha256.txt"))
        artifact_links.append((_rel_href(autopilot_dir, bundle_dir / "MANIFEST.json"), "new bundle MANIFEST.json"))

    if compare_dir is not None and compare_dir.is_dir():
        artifact_links.append(("COMPARE/compare.html", "COMPARE/compare.html"))
        artifact_links.append(("COMPARE/sha256.txt", "COMPARE/sha256.txt"))
        artifact_links.append(("COMPARE/COMPARE_MANIFEST.json", "COMPARE/COMPARE_MANIFEST.json"))

    if isinstance(baseline, dict):
        baseline_dir = baseline.get("bundle_dir")
        if isinstance(baseline_dir, Path):
            artifact_links.append((_rel_href(autopilot_dir, baseline_dir / "index.html"), "baseline bundle index.html"))

    latest_catalog = _discover_latest_catalog_html(evidence_root)
    if latest_catalog is not None:
        artifact_links.append((_rel_href(autopilot_dir, latest_catalog), "latest catalog.html"))

    autopilot_html = render_signoff_autopilot(
        manifest=manifest,
        summary_lines=summary_lines,
        artifact_links=artifact_links,
    )
    (autopilot_dir / "autopilot.html").write_text(autopilot_html + "\n", encoding="utf-8", newline="\n")
    write_sha256_manifest(autopilot_dir)

    return manifest
