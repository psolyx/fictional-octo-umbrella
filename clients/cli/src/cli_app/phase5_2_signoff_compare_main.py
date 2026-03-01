from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import platform
import sys

from cli_app.phase5_2_signoff_compare import (
    PHASE5_2_SIGNOFF_COMPARE_BEGIN,
    PHASE5_2_SIGNOFF_COMPARE_END,
    PHASE5_2_SIGNOFF_COMPARE_OK,
    PHASE5_2_SIGNOFF_COMPARE_V1,
    compare_signoff_bundles,
)


def _platform_tag() -> str:
    machine = platform.machine().lower() or "unknown"
    system = platform.system().lower() or "unknown"
    return f"{system}-{machine}"


def _default_repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def _resolve_mode(args: argparse.Namespace) -> str | None:
    dir_mode = bool(args.a_evid_dir) and bool(args.b_evid_dir)
    archive_mode = bool(args.a_archive_path) and bool(args.b_archive_path)
    if dir_mode and not archive_mode:
        return "dir"
    if archive_mode and not dir_mode:
        return "archive"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two Phase 5.2 signoff evidence bundles.")
    parser.add_argument("--a-evid-dir", default=os.environ.get("A_EVID_DIR"))
    parser.add_argument("--b-evid-dir", default=os.environ.get("B_EVID_DIR"))
    parser.add_argument("--a-archive-path", default=os.environ.get("A_ARCHIVE_PATH"))
    parser.add_argument("--b-archive-path", default=os.environ.get("B_ARCHIVE_PATH"))
    parser.add_argument("--out-evid-root", default=os.environ.get("OUT_EVID_ROOT"))
    args = parser.parse_args(argv)

    sys.stdout.write(f"{PHASE5_2_SIGNOFF_COMPARE_BEGIN}\n")
    sys.stdout.write(f"{PHASE5_2_SIGNOFF_COMPARE_V1}\n")

    try:
        mode = _resolve_mode(args)
        if mode is None:
            sys.stdout.write("compare_fail mode_invalid\n")
            return 1
        sys.stdout.write(f"mode={mode}\n")

        if os.environ.get("COMPARE_DRY_RUN") == "1":
            if mode == "dir":
                sys.stdout.write("plan verify bundle_a directory\n")
                sys.stdout.write("plan verify bundle_b directory\n")
            else:
                sys.stdout.write("plan verify bundle_a archive digest + safe extract\n")
                sys.stdout.write("plan verify bundle_b archive digest + safe extract\n")
            sys.stdout.write("plan parse MANIFEST.json + sha256.txt\n")
            sys.stdout.write("plan emit deterministic compare outputs\n")
            return 0

        repo_root = _default_repo_root()
        out_root = pathlib.Path(args.out_evid_root).resolve() if args.out_evid_root else (repo_root / "evidence").resolve()
        day = dt.datetime.utcnow().strftime("%Y-%m-%d")
        utc_stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        out_dir = out_root / f"{day}-{_platform_tag()}-compare" / f"phase5_2_signoff_compare_{utc_stamp}"

        source_a = args.a_evid_dir if mode == "dir" else args.a_archive_path
        source_b = args.b_evid_dir if mode == "dir" else args.b_archive_path
        assert source_a is not None and source_b is not None

        rc = compare_signoff_bundles(mode=mode, bundle_a=source_a, bundle_b=source_b, out_dir=str(out_dir), out=sys.stdout)
        if rc == 0:
            sys.stdout.write(f"{PHASE5_2_SIGNOFF_COMPARE_OK}\n")
        return rc
    finally:
        sys.stdout.write(f"{PHASE5_2_SIGNOFF_COMPARE_END}\n")


if __name__ == "__main__":
    raise SystemExit(main())
