from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import platform
import sys

from cli_app.phase5_2_signoff_verify_report import (
    PHASE5_2_SIGNOFF_VERIFY_REPORT_V1,
    build_verify_report_for_archive,
    build_verify_report_for_dir,
)
from cli_app.redact import redact_text
from cli_app.signoff_bundle_io import write_sha256_manifest
from cli_app.signoff_html import render_signoff_verify

PHASE5_2_SIGNOFF_VERIFY_REPORT_BEGIN = "PHASE5_2_SIGNOFF_VERIFY_REPORT_BEGIN"
PHASE5_2_SIGNOFF_VERIFY_REPORT_OK = "PHASE5_2_SIGNOFF_VERIFY_REPORT_OK"
PHASE5_2_SIGNOFF_VERIFY_REPORT_END = "PHASE5_2_SIGNOFF_VERIFY_REPORT_END"


def _platform_tag() -> str:
    machine = platform.machine().lower() or "unknown"
    system = platform.system().lower() or "unknown"
    return f"{system}-{machine}"


def _env_true(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value == "1"


def _emit(line: str) -> None:
    sys.stdout.write(f"{redact_text(line)}\n")


def main() -> int:
    repo_root = pathlib.Path(os.environ.get("REPO_ROOT", pathlib.Path.cwd())).resolve()
    out_evid_root = pathlib.Path(os.environ.get("OUT_EVID_ROOT", repo_root / "evidence")).resolve()
    evid_dir = os.environ.get("EVID_DIR")
    archive_path = os.environ.get("ARCHIVE_PATH")
    dry_run = _env_true("VERIFY_REPORT_DRY_RUN", default=False)

    _emit(PHASE5_2_SIGNOFF_VERIFY_REPORT_BEGIN)
    _emit(PHASE5_2_SIGNOFF_VERIFY_REPORT_V1)
    try:
        mode = ""
        if bool(evid_dir) ^ bool(archive_path):
            mode = "dir" if evid_dir else "archive"
        else:
            _emit("verify_report_fail mode_invalid")
            return 2

        _emit(f"mode={'dry_run' if dry_run else 'run'}")
        if dry_run:
            _emit(f"target_type={mode}")
            _emit("plan validate target and build deterministic report payload")
            _emit("plan write VERIFY_SUMMARY.txt + VERIFY_MANIFEST.json + verify.html + sha256.txt")
            _emit("plan print path-safe relative pointers")
            _emit(PHASE5_2_SIGNOFF_VERIFY_REPORT_OK)
            return 0

        try:
            if evid_dir:
                rc, report, summary_lines = build_verify_report_for_dir(pathlib.Path(evid_dir))
            else:
                assert archive_path is not None
                rc, report, summary_lines = build_verify_report_for_archive(pathlib.Path(archive_path))
        except ValueError as exc:
            _emit(f"verify_report_fail {exc}")
            return 3
        except OSError as exc:
            _emit(f"verify_report_fail {exc.__class__.__name__}")
            return 3

        now_utc = dt.datetime.now(dt.UTC)
        day = now_utc.strftime("%Y-%m-%d")
        stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
        verify_dir = out_evid_root / f"{day}-{_platform_tag()}-verify" / f"phase5_2_signoff_verify_report_{stamp}"
        verify_dir.mkdir(parents=True, exist_ok=False)

        (verify_dir / "VERIFY_SUMMARY.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n")
        with (verify_dir / "VERIFY_MANIFEST.json").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(report, indent=2, sort_keys=True))
            handle.write("\n")

        artifact_links = [
            ("VERIFY_SUMMARY.txt", "VERIFY_SUMMARY.txt"),
            ("VERIFY_MANIFEST.json", "VERIFY_MANIFEST.json"),
            ("sha256.txt", "sha256.txt"),
        ]
        (verify_dir / "verify.html").write_text(
            render_signoff_verify(report=report, summary_lines=summary_lines, artifact_links=artifact_links) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        write_sha256_manifest(verify_dir, manifest_name="sha256.txt")

        verify_dir_rel = pathlib.Path(os.path.relpath(verify_dir, repo_root)).as_posix()
        _emit(f"verify_dir_name={verify_dir.name}")
        _emit(f"verify_dir_rel={verify_dir_rel}")
        _emit(f"verify_html_rel={verify_dir_rel}/verify.html")
        _emit(f"target_type={report.get('target_type', '')}")
        _emit(f"target_name={report.get('target_name', '')}")
        if rc == 0:
            _emit(PHASE5_2_SIGNOFF_VERIFY_REPORT_OK)
        return rc
    finally:
        _emit(PHASE5_2_SIGNOFF_VERIFY_REPORT_END)


if __name__ == "__main__":
    raise SystemExit(main())
