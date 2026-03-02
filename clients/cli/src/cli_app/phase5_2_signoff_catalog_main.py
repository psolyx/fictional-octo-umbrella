from __future__ import annotations

import datetime as dt
import os
import pathlib
import platform
import sys

from cli_app.phase5_2_signoff_catalog import (
    PHASE5_2_SIGNOFF_CATALOG_BEGIN,
    PHASE5_2_SIGNOFF_CATALOG_END,
    PHASE5_2_SIGNOFF_CATALOG_OK,
    PHASE5_2_SIGNOFF_CATALOG_V1,
    scan_signoff_catalog,
    write_signoff_catalog_outputs,
)


def _platform_tag() -> str:
    machine = platform.machine().lower() or "unknown"
    system = platform.system().lower() or "unknown"
    return f"{system}-{machine}"


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[4]


def main() -> int:
    sys.stdout.write(f"{PHASE5_2_SIGNOFF_CATALOG_BEGIN}\n")
    sys.stdout.write(f"{PHASE5_2_SIGNOFF_CATALOG_V1}\n")
    try:
        repo_root = _repo_root()
        evidence_root = pathlib.Path(os.environ.get("EVIDENCE_ROOT", repo_root / "evidence")).resolve()
        out_evid_root = pathlib.Path(os.environ.get("OUT_EVID_ROOT", repo_root / "evidence")).resolve()
        max_entries = int(os.environ.get("MAX_ENTRIES", "200"))

        sys.stdout.write(f"evidence_root_basename={evidence_root.name}\n")

        if os.environ.get("CATALOG_DRY_RUN") == "1":
            sys.stdout.write("plan discover bundle and compare run directories\n")
            sys.stdout.write("plan parse manifests and derive summary fields\n")
            sys.stdout.write("plan render deterministic catalog manifest/html/sha256\n")
            sys.stdout.write(f"{PHASE5_2_SIGNOFF_CATALOG_OK}\n")
            return 0

        now_utc = dt.datetime.now(dt.UTC)
        day = now_utc.strftime("%Y-%m-%d")
        stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
        out_dir = out_evid_root / f"{day}-{_platform_tag()}-catalog" / f"phase5_2_signoff_catalog_{stamp}"

        catalog = scan_signoff_catalog(evidence_root=evidence_root, max_entries=max_entries)
        write_signoff_catalog_outputs(catalog, evidence_root=evidence_root, out_dir=out_dir)
        sys.stdout.write(f"catalog_dir={out_dir.as_posix()}\n")
        sys.stdout.write(f"{PHASE5_2_SIGNOFF_CATALOG_OK}\n")
        return 0
    except (OSError, ValueError):
        return 1
    finally:
        sys.stdout.write(f"{PHASE5_2_SIGNOFF_CATALOG_END}\n")


if __name__ == "__main__":
    raise SystemExit(main())
