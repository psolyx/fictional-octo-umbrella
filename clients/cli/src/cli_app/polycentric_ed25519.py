"""Wrapper for invoking the Go-based ed25519 helper."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Tuple

MIN_GO_VERSION: Tuple[int, int] = (1, 22)


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        candidate = parent if parent.is_dir() else parent.parent
        tool_dir = candidate / "tools" / "polycentric_ed25519"
        if tool_dir.is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing tools/polycentric_ed25519")


def parse_go_version(raw: str) -> Tuple[int, int, int]:
    match = re.search(r"go(\d+)\.(\d+)(?:\.(\d+))?", raw)
    if not match:
        raise ValueError(f"Unable to parse Go version from: {raw!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def detect_go_version(go_path: str) -> Tuple[int, int, int]:
    try:
        env_output = subprocess.check_output([go_path, "env", "GOVERSION"], text=True).strip()
    except subprocess.CalledProcessError:
        env_output = ""

    if env_output:
        return parse_go_version(env_output)

    version_output = subprocess.check_output([go_path, "version"], text=True).strip()
    return parse_go_version(version_output)


def ensure_go_ready() -> str:
    go_path = shutil.which("go")
    if not go_path:
        raise RuntimeError("Go toolchain is required but was not found in PATH")

    version = detect_go_version(go_path)
    if (version[0], version[1]) < MIN_GO_VERSION:
        raise RuntimeError(
            f"Go >= {MIN_GO_VERSION[0]}.{MIN_GO_VERSION[1]} is required (found {version[0]}.{version[1]}.{version[2]})"
        )

    return go_path


def _tool_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update({"GOTOOLCHAIN": "local", "GOFLAGS": "-mod=vendor"})
    return env


def _run_tool(subcommand: str, args: Iterable[str], payload: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    go_path = ensure_go_ready()
    repo_root = find_repo_root()
    tool_dir = repo_root / "tools" / "polycentric_ed25519"
    cmd = [go_path, "run", "-mod=vendor", "./cmd/polycentric-ed25519", subcommand, *list(args)]
    return subprocess.run(
        cmd,
        cwd=str(tool_dir),
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=_tool_env(),
    )


def generate() -> dict[str, str]:
    result = _run_tool("gen", [])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="ignore"))
    return json.loads(result.stdout.decode("utf-8"))


def derive_pubkey(seed_b64: str) -> dict[str, str]:
    result = _run_tool("pubkey", ["--seed-b64", seed_b64])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="ignore"))
    return json.loads(result.stdout.decode("utf-8"))


def sign(seed_b64: str, canonical_bytes: bytes) -> dict[str, str]:
    result = _run_tool("sign", ["--seed-b64", seed_b64], payload=canonical_bytes)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="ignore"))
    return json.loads(result.stdout.decode("utf-8"))


def verify(pub_key_b64: str, sig_b64: str, canonical_bytes: bytes) -> bool:
    result = _run_tool(
        "verify",
        ["--pub-key-b64", pub_key_b64, "--sig-b64", sig_b64],
        payload=canonical_bytes,
    )
    return result.returncode == 0
