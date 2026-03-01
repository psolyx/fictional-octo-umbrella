from __future__ import annotations

import os
import pathlib
import sys

from cli_app.phase5_2_signoff_bundle import run_signoff_bundle


def main() -> int:
    repo_root = pathlib.Path(os.environ.get("REPO_ROOT", pathlib.Path(__file__).resolve().parents[4])).resolve()
    out_evid_root = pathlib.Path(os.environ.get("OUT_EVID_ROOT", repo_root / "evidence")).resolve()
    base_url = os.environ.get("BASE_URL")
    dry_run = os.environ.get("SIGNOFF_DRY_RUN") == "1"
    rc, bundle_dir = run_signoff_bundle(
        repo_root=str(repo_root),
        out_evid_root=str(out_evid_root),
        base_url=base_url,
        dry_run=dry_run,
        out=sys.stdout,
    )
    if bundle_dir is not None:
        sys.stdout.write(f"evidence_dir={bundle_dir.as_posix()}\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
