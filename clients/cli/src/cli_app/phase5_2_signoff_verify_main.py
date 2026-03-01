from __future__ import annotations

import argparse
import os
import pathlib
import sys

from cli_app.phase5_2_signoff_verify import (
    PHASE5_2_SIGNOFF_VERIFY_BEGIN,
    PHASE5_2_SIGNOFF_VERIFY_END,
    PHASE5_2_SIGNOFF_VERIFY_OK,
    PHASE5_2_SIGNOFF_VERIFY_V1,
    verify_signoff_bundle,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a Phase 5.2 signoff evidence directory.")
    parser.add_argument("--evid-dir", default=os.environ.get("EVID_DIR"), help="Path to signoff evidence directory")
    args = parser.parse_args(argv)

    sys.stdout.write(f"{PHASE5_2_SIGNOFF_VERIFY_BEGIN}\n")
    sys.stdout.write(f"{PHASE5_2_SIGNOFF_VERIFY_V1}\n")

    try:
        dry_run = os.environ.get("VERIFY_DRY_RUN") == "1"
        if dry_run:
            sys.stdout.write("plan validate required files\n")
            sys.stdout.write("plan validate summary markers against manifest success\n")
            sys.stdout.write("plan validate sha256 strict ordering and integrity\n")
            sys.stdout.write("plan validate manifest structure and status consistency\n")
            sys.stdout.write("plan validate redaction forbidden token scan\n")
            sys.stdout.write(f"{PHASE5_2_SIGNOFF_VERIFY_OK}\n")
            return 0

        if not args.evid_dir:
            sys.stdout.write("verify_fail missing_evid_dir\n")
            return 2

        evid_dir = pathlib.Path(args.evid_dir).resolve()
        sys.stdout.write(f"run evid_dir={evid_dir.as_posix()}\n")
        return verify_signoff_bundle(str(evid_dir), out=sys.stdout)
    finally:
        sys.stdout.write(f"{PHASE5_2_SIGNOFF_VERIFY_END}\n")


if __name__ == "__main__":
    raise SystemExit(main())
