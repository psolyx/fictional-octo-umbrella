from __future__ import annotations

import os
import pathlib
import sys

from cli_app.phase5_2_signoff_autopilot import (
    PHASE5_2_SIGNOFF_AUTOPILOT_BEGIN,
    PHASE5_2_SIGNOFF_AUTOPILOT_END,
    PHASE5_2_SIGNOFF_AUTOPILOT_OK,
    PHASE5_2_SIGNOFF_AUTOPILOT_V1,
    run_autopilot,
)


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
    dry_run = _env_true("AUTOPILOT_DRY_RUN", default=False)

    sys.stdout.write(f"{PHASE5_2_SIGNOFF_AUTOPILOT_BEGIN}\n")
    sys.stdout.write(f"{PHASE5_2_SIGNOFF_AUTOPILOT_V1}\n")
    try:
        sys.stdout.write(f"mode={'dry_run' if dry_run else 'run'}\n")
        sys.stdout.write(f"evidence_root_basename={evidence_root.name}\n")
        if dry_run:
            sys.stdout.write("plan bundle_generate_and_archive\n")
            sys.stdout.write("plan verify_new_bundle_prefer_archive\n")
            sys.stdout.write("plan compare_against_latest_pass_bundle\n")
            sys.stdout.write("plan write_autopilot_summary_manifest_sha256\n")
            sys.stdout.write(f"{PHASE5_2_SIGNOFF_AUTOPILOT_OK}\n")
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
        exit_code = int(manifest.get("exit_code", 1))
        if exit_code == 0:
            sys.stdout.write(f"{PHASE5_2_SIGNOFF_AUTOPILOT_OK}\n")
        return exit_code
    finally:
        sys.stdout.write(f"{PHASE5_2_SIGNOFF_AUTOPILOT_END}\n")


if __name__ == "__main__":
    raise SystemExit(main())

