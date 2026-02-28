"""CLI entrypoint for deterministic Phase 5.2 static audit."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from cli_app.phase5_2_static_audit import PHASE5_2_STATIC_AUDIT_END, run_audit


def _find_repo_root() -> Path:
    env_root = os.environ.get("REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()
    current = Path(__file__).resolve()
    for parent in [current, *current.parents]:
        if (parent / "clients").exists() and (parent / "gateway").exists() and (parent / "ROADMAP.md").exists():
            return parent
    return current.parents[4]


def main() -> int:
    repo_root = _find_repo_root()
    try:
        return run_audit(str(repo_root), out=sys.stdout)
    except Exception:
        print(
            "check=0 FAIL phase5_2_static_audit_main reason=unexpected_exception file=clients/cli/src/cli_app/phase5_2_static_audit_main.py"
        )
        print(PHASE5_2_STATIC_AUDIT_END)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
