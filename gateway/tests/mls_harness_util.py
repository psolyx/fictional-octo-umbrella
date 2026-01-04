import atexit
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "tools" / "mls_harness"

_HARNESS_BUILD_DIR: Optional[Path] = None
_HARNESS_BINARY_PATH: Optional[Path] = None


def _parse_go_version(raw: str) -> Optional[Tuple[int, int, int]]:
    match = re.search(r"go(\d+)\.(\d+)(?:\.(\d+))?", raw)
    if not match:
        return None

    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def _get_go_version(go_bin: str) -> Optional[Tuple[int, int, int]]:
    for args in ([go_bin, "env", "GOVERSION"], [go_bin, "version"]):
        try:
            output = subprocess.check_output(args, text=True).strip()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue

        parsed = _parse_go_version(output)
        if parsed:
            return parsed

    return None


def _require_go(min_version: Tuple[int, int, int] = (1, 22, 0)) -> str:
    go_bin = shutil.which("go")
    if not go_bin:
        raise unittest.SkipTest("Go toolchain not available")

    go_version = _get_go_version(go_bin)
    if not go_version:
        raise unittest.SkipTest("Unable to determine Go version")

    if go_version < min_version:
        raise unittest.SkipTest(f"Go >= {'.'.join(map(str, min_version))} required for MLS harness tests")

    return go_bin


def _base_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    merged: Dict[str, str] = dict(os.environ)
    if env:
        merged.update(env)

    merged.setdefault("GOTOOLCHAIN", "local")
    merged.setdefault("GOFLAGS", "-mod=vendor")
    merged.setdefault("GOMAXPROCS", "1")
    merged.setdefault("GOMEMLIMIT", "700MiB")
    return merged


def make_harness_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    return _base_env(env)


def ensure_harness_binary(timeout_s: float = 120.0) -> Path:
    global _HARNESS_BINARY_PATH, _HARNESS_BUILD_DIR

    if _HARNESS_BINARY_PATH and _HARNESS_BINARY_PATH.exists():
        return _HARNESS_BINARY_PATH

    go_bin = _require_go()

    if not _HARNESS_BUILD_DIR:
        _HARNESS_BUILD_DIR = Path(tempfile.mkdtemp(prefix="mls-harness-"))
        atexit.register(shutil.rmtree, _HARNESS_BUILD_DIR, ignore_errors=True)

    harness_binary = _HARNESS_BUILD_DIR / "mls-harness"
    env = _base_env()
    proc = subprocess.run(
        [go_bin, "build", "-p", "1", "-o", harness_binary, "./cmd/mls-harness"],
        check=False,
        capture_output=True,
        text=True,
        cwd=HARNESS_DIR,
        env=env,
        timeout=timeout_s,
    )

    if proc.returncode != 0:
        raise AssertionError(
            "Failed to build MLS harness binary:\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )

    _HARNESS_BINARY_PATH = harness_binary
    return harness_binary


def run_harness(
    args: Sequence[str],
    *,
    harness_bin: Optional[Path] = None,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    timeout_s: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    binary = harness_bin or ensure_harness_binary()
    proc = subprocess.run(
        [str(binary), *[str(arg) for arg in args]],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_base_env(env),
        timeout=timeout_s,
    )
    return proc


__all__ = [
    "HARNESS_DIR",
    "ensure_harness_binary",
    "make_harness_env",
    "run_harness",
]
