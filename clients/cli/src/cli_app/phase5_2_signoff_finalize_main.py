from __future__ import annotations

import os
import pathlib
import sys

from cli_app.phase5_2_signoff_autopilot import run_autopilot
from cli_app.phase5_2_signoff_finalize import (
    PHASE5_2_SIGNOFF_FINALIZE_BEGIN,
    PHASE5_2_SIGNOFF_FINALIZE_END,
    PHASE5_2_SIGNOFF_FINALIZE_OK,
    PHASE5_2_SIGNOFF_FINALIZE_V1,
    write_phase5_2_signoff_txt,
)
from cli_app.redact import redact_text


def _env_true(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value == "1"


def main() -> int:
    repo_root = pathlib.Path(os.environ.get("REPO_ROOT", pathlib.Path.cwd())).resolve()
    out_evid_root = pathlib.Path(os.environ.get("OUT_EVID_ROOT", repo_root / "evidence")).resolve()
    evidence_root = pathlib.Path(os.environ.get("EVIDENCE_ROOT", repo_root / "evidence")).resolve()
    base_url = os.environ.get("BASE_URL")
    no_archive = _env_true("SIGNOFF_NO_ARCHIVE", default=False)
    prefer_archive = _env_true("AUTOPILOT_PREFER_ARCHIVE", default=True)
    compare_prefer_archive = _env_true("AUTOPILOT_COMPARE_PREFER_ARCHIVE", default=True)
    dry_run = _env_true("FINALIZE_DRY_RUN", default=False)

    def emit(line: str) -> None:
        sys.stdout.write(f"{redact_text(line)}\n")

    emit(PHASE5_2_SIGNOFF_FINALIZE_BEGIN)
    emit(PHASE5_2_SIGNOFF_FINALIZE_V1)
    try:
        emit(f"mode={'dry_run' if dry_run else 'run'}")
        emit(f"evidence_root_basename={evidence_root.name}")
        if dry_run:
            emit("plan run_autopilot")
            emit("plan write_phase5_2_signoff_txt")
            emit("plan print_path_safe_output_pointers")
            emit(PHASE5_2_SIGNOFF_FINALIZE_OK)
            return 0

        manifest = run_autopilot(
            repo_root=repo_root,
            out_evid_root=out_evid_root,
            evidence_root=evidence_root,
            base_url=base_url,
            prefer_archive=prefer_archive,
            compare_prefer_archive=compare_prefer_archive,
            no_archive=no_archive,
            out=sys.stdout,
        )
        autopilot_dir_rel = str(manifest.get("autopilot_dir_rel", ""))
        autopilot_dir_name = str(manifest.get("autopilot_dir_name", ""))
        autopilot_html_name = str(manifest.get("autopilot_html_name", "autopilot.html"))

        autopilot_dir = (repo_root / autopilot_dir_rel).resolve()
        signoff_path = write_phase5_2_signoff_txt(autopilot_dir=autopilot_dir, manifest=manifest)

        emit(f"autopilot_dir_name={autopilot_dir_name}")
        emit(f"autopilot_dir_rel={autopilot_dir_rel}")
        emit(f"autopilot_html_rel={autopilot_dir_rel}/{autopilot_html_name}")
        emit(f"signoff_txt_rel={autopilot_dir_rel}/{signoff_path.name}")

        exit_code = int(manifest.get("exit_code", 1))
        if exit_code == 0:
            emit(PHASE5_2_SIGNOFF_FINALIZE_OK)
        return exit_code
    finally:
        emit(PHASE5_2_SIGNOFF_FINALIZE_END)


if __name__ == "__main__":
    raise SystemExit(main())
