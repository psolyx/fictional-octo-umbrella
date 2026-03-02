from __future__ import annotations

import os
from pathlib import Path

from cli_app.redact import redact_text

PHASE5_2_SIGNOFF_FINALIZE_BEGIN = "PHASE5_2_SIGNOFF_FINALIZE_BEGIN"
PHASE5_2_SIGNOFF_FINALIZE_END = "PHASE5_2_SIGNOFF_FINALIZE_END"
PHASE5_2_SIGNOFF_FINALIZE_OK = "PHASE5_2_SIGNOFF_FINALIZE_OK"
PHASE5_2_SIGNOFF_FINALIZE_V1 = "PHASE5_2_SIGNOFF_FINALIZE_V1"


def _line(key: str, value: object) -> str:
    return f"{key}={redact_text(str(value))}"


def render_phase5_2_signoff_txt(
    *, manifest: dict, sha256_manifest_rel: str, autopilot_dir_name: str, compare_dir_name: str | None
) -> str:
    autopilot_html_name = redact_text(str(manifest.get("autopilot_html_name", "autopilot.html")))
    summary_name = "AUTOPILOT_SUMMARY.txt"
    manifest_name = "AUTOPILOT_MANIFEST.json"
    signoff_txt_name = redact_text(str(manifest.get("signoff_txt_name", "PHASE5_2_SIGNOFF.txt")))

    lines = [
        PHASE5_2_SIGNOFF_FINALIZE_BEGIN,
        PHASE5_2_SIGNOFF_FINALIZE_V1,
        _line("autopilot_dir_name", autopilot_dir_name),
        _line("autopilot_html_name", autopilot_html_name),
        _line("signoff_txt_name", signoff_txt_name),
        _line("autopilot_summary_name", summary_name),
        _line("autopilot_manifest_name", manifest_name),
        _line("autopilot_sha256_rel", sha256_manifest_rel),
        _line("bundle_dir_name", manifest.get("bundle_dir_name", "none")),
        _line("archive_name", manifest.get("archive_name", "none")),
        _line("archive_sha256_name", manifest.get("archive_sha256_name", "none")),
        _line("bundle_sha256_name", manifest.get("bundle_sha256_name", "sha256.txt")),
        _line("bundle_manifest_name", manifest.get("bundle_manifest_name", "MANIFEST.json")),
        _line("baseline_bundle_dir_name", manifest.get("baseline_bundle_dir_name", "none")),
        _line("compare_result", manifest.get("compare_result", "SKIPPED")),
        _line("regression_count", manifest.get("regression_count", 0)),
        _line("compare_dir_name", compare_dir_name if compare_dir_name else "none"),
    ]

    if compare_dir_name:
        lines.extend(
            [
                _line("compare_summary_rel", f"{compare_dir_name}/COMPARE_SUMMARY.txt"),
                _line("compare_manifest_rel", f"{compare_dir_name}/COMPARE_MANIFEST.json"),
                _line("compare_sha256_rel", f"{compare_dir_name}/sha256.txt"),
                _line("compare_html_rel", f"{compare_dir_name}/compare.html"),
            ]
        )

    lines.extend([PHASE5_2_SIGNOFF_FINALIZE_OK, PHASE5_2_SIGNOFF_FINALIZE_END])
    return "\n".join(lines) + "\n"


def write_phase5_2_signoff_txt(*, autopilot_dir: Path, manifest: dict) -> Path:
    signoff_path = autopilot_dir / "PHASE5_2_SIGNOFF.txt"
    compare_dir = autopilot_dir / "COMPARE"
    compare_dir_name = compare_dir.name if compare_dir.is_dir() else None
    rendered = render_phase5_2_signoff_txt(
        manifest=manifest,
        sha256_manifest_rel="sha256.txt",
        autopilot_dir_name=autopilot_dir.name,
        compare_dir_name=compare_dir_name,
    )
    signoff_path.write_text(rendered, encoding="utf-8", newline="\n")
    return signoff_path
