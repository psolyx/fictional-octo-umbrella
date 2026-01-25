"""CLI POC for running MLS harness scenarios locally."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO, Iterable, Tuple

from cli_app import dm_envelope, gateway_client, gateway_store, identity_store, interop_transcript, profile_paths

MIN_GO_VERSION: Tuple[int, int] = (1, 22)


def find_repo_root() -> Path:
    """Find the repository root by walking parents from this file."""

    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        candidate = parent if parent.is_dir() else parent.parent
        harness_dir = candidate / "tools" / "mls_harness"
        if harness_dir.is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing tools/mls_harness")


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


def _harness_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GOTOOLCHAIN": "local",
            "GOFLAGS": "-mod=vendor",
            "GOMAXPROCS": "1",
            "GOMEMLIMIT": "700MiB",
        }
    )
    return env


def _harness_binary_path(repo_root: Path) -> Path:
    return repo_root / "tools" / "mls_harness" / ".cache" / "mls-harness"


def _build_harness_binary(repo_root: Path) -> Path:
    go_path = ensure_go_ready()
    harness_dir = repo_root / "tools" / "mls_harness"
    harness_bin = _harness_binary_path(repo_root)
    harness_bin.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        go_path,
        "build",
        "-p",
        "1",
        "-o",
        str(harness_bin),
        "./cmd/mls-harness",
    ]

    result = subprocess.run(
        cmd,
        cwd=str(harness_dir),
        env=_harness_env(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Failed to build MLS harness binary:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
        )

    try:
        harness_bin.chmod(0o755)
    except OSError:
        pass

    return harness_bin


def _ensure_harness_binary(repo_root: Path) -> Path:
    harness_bin = _harness_binary_path(repo_root)
    if harness_bin.exists():
        return harness_bin
    return _build_harness_binary(repo_root)


def run_harness(subcommand: str, extra_args: Iterable[str]) -> int:
    repo_root = find_repo_root()
    harness_dir = repo_root / "tools" / "mls_harness"
    harness_bin = _ensure_harness_binary(repo_root)
    cmd = [str(harness_bin), subcommand, *extra_args]

    result = subprocess.run(
        cmd,
        cwd=str(harness_dir),
        env=_harness_env(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def _run_harness_capture(subcommand: str, extra_args: Iterable[str]) -> str:
    returncode, stdout, stderr = _run_harness_capture_with_status(subcommand, extra_args)
    if returncode != 0:
        sys.stderr.write(stderr)
        raise RuntimeError(f"harness {subcommand} failed")
    return stdout


def _run_harness_capture_with_status(subcommand: str, extra_args: Iterable[str]) -> tuple[int, str, str]:
    repo_root = find_repo_root()
    harness_dir = repo_root / "tools" / "mls_harness"
    harness_bin = _ensure_harness_binary(repo_root)
    cmd = [str(harness_bin), subcommand, *extra_args]

    result = subprocess.run(
        cmd,
        cwd=str(harness_dir),
        env=_harness_env(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.returncode, result.stdout, result.stderr


def _first_nonempty_line(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    raise RuntimeError("harness output was empty")


def _msg_id_for_env(env_b64: str) -> str:
    env_bytes = base64.b64decode(env_b64)
    return hashlib.sha256(env_bytes).hexdigest()


def _default_room_group_id_b64() -> str:
    return base64.b64encode(b"room-group").decode("utf-8")


def _default_dm_group_id_b64() -> str:
    return base64.b64encode(b"dm-group").decode("utf-8")


def _state_dir_has_data(state_dir: Path) -> bool:
    if not state_dir.exists():
        return False
    if not state_dir.is_dir():
        raise RuntimeError(f"state_dir is not a directory: {state_dir}")
    return any(state_dir.iterdir())


def _ensure_initiator_state(state_dir: str, seed_keypackage: int) -> None:
    state_path = Path(state_dir)
    if _state_dir_has_data(state_path):
        return
    _run_harness_capture(
        "dm-keypackage",
        [
            "--state-dir",
            state_dir,
            "--name",
            "initiator",
            "--seed",
            str(seed_keypackage),
        ],
    )


def _extract_http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        return str(exc)
    if not raw:
        return str(exc)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    message = payload.get("message")
    return str(message) if message else raw


def _is_uninitialized_commit_error(message: str) -> bool:
    lowered = message.lower()
    return "participant state not initialized" in lowered or "state not initialized" in lowered


def _pending_commits_path(state_dir: str) -> Path:
    return Path(state_dir) / "pending_dm_commits.json"


def _load_pending_commits(path: Path) -> dict[int, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    pending = data.get("pending", {})
    if not isinstance(pending, dict):
        return {}
    parsed: dict[int, str] = {}
    for key, value in pending.items():
        try:
            seq = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, str):
            parsed[seq] = value
    return parsed


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, indent=2, sort_keys=True)

    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _load_json_payload(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing JSON file: {path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return payload


def _save_pending_commits(path: Path, pending: dict[int, str]) -> None:
    if not pending:
        if path.exists():
            path.unlink()
        return
    payload = {"pending": {str(seq): payload_b64 for seq, payload_b64 in sorted(pending.items())}}
    _atomic_write_json(path, payload)


def _buffer_pending_commit(path: Path, pending: dict[int, str], seq: int, payload_b64: str) -> bool:
    if seq in pending:
        return False
    pending[seq] = payload_b64
    _save_pending_commits(path, pending)
    return True


def _flush_pending_commits(state_dir: str, pending: dict[int, str], pending_path: Path) -> None:
    for seq in sorted(pending):
        payload_b64 = pending[seq]
        returncode, stdout, stderr = _run_harness_capture_with_status(
            "dm-commit-apply",
            [
                "--state-dir",
                state_dir,
                "--commit",
                payload_b64,
            ],
        )
        if returncode != 0:
            message = stderr.strip() or stdout.strip()
            sys.stderr.write(message + "\n" if message else stderr)
            raise RuntimeError("harness dm-commit-apply failed")
        del pending[seq]
        _save_pending_commits(pending_path, pending)


def _send_envelope(base_url: str, session_token: str, conv_id: str, env_b64: str) -> int:
    msg_id = _msg_id_for_env(env_b64)
    response = gateway_client.inbox_send(base_url, session_token, conv_id, msg_id, env_b64)
    return int(response["seq"])


def _poll_keypackage(
    base_url: str,
    session_token: str,
    user_id: str,
    timeout_s: int,
    interval_ms: int,
) -> str:
    deadline = time.time() + timeout_s
    while True:
        response = gateway_client.keypackages_fetch(base_url, session_token, user_id, 1)
        keypackages = response.get("keypackages", [])
        if keypackages:
            return str(keypackages[0])
        if time.time() >= deadline:
            raise RuntimeError(f"Timed out waiting for KeyPackage for user {user_id}")
        time.sleep(interval_ms / 1000)


def _phase5_room_smoke_plan(args: argparse.Namespace) -> dict[str, object]:
    base_url = args.base_url or "<stored session base_url>"
    command_prefix = "python -m cli_app.mls_poc"
    steps: list[dict[str, object]] = [
        {
            "step": "start_session",
            "commands": [f"{command_prefix} gw-start --base-url {base_url}"],
        },
        {
            "step": "create_room",
            "gateway_request": {
                "method": "POST",
                "path": "/v1/rooms/create",
                "body": {
                    "conv_id": args.conv_id,
                    "members": ["<my_user_id>", *args.peer_user_id],
                },
            },
        },
        {
            "step": "wait_for_keypackages",
            "gateway_request": {
                "method": "POST",
                "path": "/v1/keypackages/fetch",
                "body": {
                    "count": 1,
                    "user_id": "<peer_user_id>",
                },
            },
        },
        {
            "step": "send_envelopes",
            "gateway_request": {
                "method": "POST",
                "path": "/v1/inbox",
                "body": {
                    "conv_id": args.conv_id,
                    "env": "<base64 envelope>",
                    "msg_id": "sha256(env_bytes)",
                },
            },
            "envelopes": [
                {"kind": 1, "name": "welcome", "msg_id": "sha256(env_bytes)"},
                {"kind": 2, "name": "commit", "msg_id": "sha256(env_bytes)"},
                {"kind": 3, "name": "app", "msg_id": "sha256(env_bytes)"},
            ],
        },
        {
            "step": "web_peer_actions",
            "instructions": [
                "Peer publishes KeyPackage in the web UI.",
                "Peer joins the room after Welcome appears in their inbox.",
            ],
        },
    ]
    add_peer_user_ids = args.add_peer_user_id or []
    if add_peer_user_ids:
        steps.extend(
            [
                {
                    "step": "wait_for_add_keypackages",
                    "gateway_request": {
                        "method": "POST",
                        "path": "/v1/keypackages/fetch",
                        "body": {
                            "count": 1,
                            "user_id": "<add_peer_user_id>",
                        },
                    },
                },
                {
                    "step": "group_add_send_envelopes",
                    "gateway_request": {
                        "method": "POST",
                        "path": "/v1/inbox",
                        "body": {
                            "conv_id": args.conv_id,
                            "env": "<base64 envelope>",
                            "msg_id": "sha256(env_bytes)",
                        },
                    },
                    "envelopes": [
                        {"kind": 2, "name": "add_proposal", "msg_id": "sha256(env_bytes)"},
                        {"kind": 1, "name": "add_welcome", "msg_id": "sha256(env_bytes)"},
                        {"kind": 2, "name": "add_commit", "msg_id": "sha256(env_bytes)"},
                    ],
                },
                {
                    "step": "send_second_app",
                    "gateway_request": {
                        "method": "POST",
                        "path": "/v1/inbox",
                        "body": {
                            "conv_id": args.conv_id,
                            "env": "<base64 envelope>",
                            "msg_id": "sha256(env_bytes)",
                        },
                    },
                    "envelopes": [
                        {"kind": 3, "name": "app2", "msg_id": "sha256(env_bytes)"},
                    ],
                },
            ]
        )
    return {
        "command": "gw-phase5-room-smoke",
        "conv_id": args.conv_id,
        "dry_run": True,
        "group_id_b64": args.group_id_b64,
        "kp_poll": {
            "interval_ms": args.kp_poll_interval_ms,
            "seconds": args.kp_poll_seconds,
        },
        "add_peer_user_ids": add_peer_user_ids,
        "peer_user_ids": args.peer_user_id,
        "plaintext2": args.plaintext2,
        "outputs": {
            "print_web_cli_block": args.print_web_cli_block,
            "transcript_out": args.transcript_out,
        },
        "preconditions": [
            "Run gw-start (or gw-resume) to store session_token and base_url.",
            "Peers must publish KeyPackages (web client or gw-kp-publish).",
            "Initiator needs MLS state in --state-dir (seed_keypackage is deterministic).",
        ],
        "seeds": {
            "app": args.seed_app,
            "app2": args.seed_app2,
            "group_add": args.seed_group_add,
            "group_init": args.seed_group_init,
            "keypackage": args.seed_keypackage,
        },
        "steps": steps,
    }


def build_parser() -> argparse.ArgumentParser:
    repo_root = find_repo_root()
    default_vector = repo_root / "tools" / "mls_harness" / "vectors" / "dm_smoke_v1.json"

    parser = argparse.ArgumentParser(description="MLS DM POC using the Go harness")
    parser.add_argument(
        "--profile",
        default="default",
        help="Profile name for storing identity/session/cursor state (default: default)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    vectors = subparsers.add_parser("vectors", help="Verify deterministic vector output")
    vectors.add_argument(
        "--vector-file",
        default=str(default_vector),
        help="Path to vector JSON file (default: repo vectors/dm_smoke_v1.json)",
    )

    smoke = subparsers.add_parser("smoke", help="Run short persistence scenario")
    smoke.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    smoke.add_argument("--iterations", type=int, default=50, help="Message iterations per participant (default: 50)")
    smoke.add_argument("--save-every", type=int, default=10, help="Checkpoint interval (default: 10)")

    soak = subparsers.add_parser("soak", help="Run long soak persistence scenario")
    soak.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    soak.add_argument("--iterations", type=int, default=1000, help="Message iterations per participant (default: 1000)")
    soak.add_argument("--save-every", type=int, default=50, help="Checkpoint interval (default: 50)")

    whoami = subparsers.add_parser("whoami", help="Show local Polycentric identity and device")
    whoami.add_argument(
        "--identity-file",
        default=None,
        help="Path to identity JSON (defaults to the profile identity path)",
    )

    gw_start = subparsers.add_parser("gw-start", help="Start a gateway session and persist tokens")
    gw_start.add_argument("--base-url", required=True, help="Gateway base URL (required)")

    gw_resume = subparsers.add_parser("gw-resume", help="Resume a gateway session and rotate tokens")
    gw_resume.add_argument("--base-url", required=True, help="Gateway base URL (required)")

    gw_send = subparsers.add_parser("gw-send", help="Send an encrypted envelope to the gateway inbox")
    gw_send.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_send.add_argument("--msg-id", required=True, help="Message id (required)")
    gw_send.add_argument("--env-b64", required=True, help="Ciphertext envelope (base64, required)")
    gw_send.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_ack = subparsers.add_parser("gw-ack", help="Acknowledge a conversation sequence")
    gw_ack.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_ack.add_argument("--seq", required=True, type=int, help="Sequence number to acknowledge (required)")
    gw_ack.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_tail = subparsers.add_parser("gw-tail", help="Tail gateway SSE replay for a conversation")
    gw_tail.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_tail.add_argument("--from-seq", type=int, help="Sequence to replay from (defaults to stored cursor)")
    gw_tail.add_argument("--max-events", type=int, help="Stop after emitting this many events")
    gw_tail.add_argument(
        "--idle-timeout-s",
        type=float,
        nargs="?",
        const=5.0,
        default=None,
        help="Stop if idle for this many seconds (default: none; if flag present defaults to 5.0)",
    )
    gw_tail.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_kp_publish = subparsers.add_parser("gw-kp-publish", help="Publish KeyPackages to the gateway directory")
    gw_kp_publish.add_argument("--count", type=int, required=True, help="Number of KeyPackages to publish (required)")
    gw_kp_publish.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_kp_publish.add_argument("--name", default="participant", help="Participant name (default: participant)")
    gw_kp_publish.add_argument("--seed-base", type=int, default=1337, help="Seed base (default: 1337)")
    gw_kp_publish.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_kp_fetch = subparsers.add_parser("gw-kp-fetch", help="Fetch KeyPackages from the gateway directory")
    gw_kp_fetch.add_argument("--user-id", required=True, help="User id to fetch from (required)")
    gw_kp_fetch.add_argument("--count", type=int, required=True, help="Number of KeyPackages to fetch (required)")
    gw_kp_fetch.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow zero KeyPackages without exiting non-zero (default: fail fast)",
    )
    gw_kp_fetch.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_dm_create = subparsers.add_parser("gw-dm-create", help="Create a DM conversation via the gateway")
    gw_dm_create.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_dm_create.add_argument("--peer-user-id", required=True, help="Peer user id (required)")
    gw_dm_create.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_room_create = subparsers.add_parser("gw-room-create", help="Create a room conversation via the gateway")
    gw_room_create.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_room_create.add_argument(
        "--member-user-id",
        required=True,
        action="append",
        help="Member user id to add (repeatable, required)",
    )
    gw_room_create.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_room_invite = subparsers.add_parser("gw-room-invite", help="Invite members to a room via the gateway")
    gw_room_invite.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_room_invite.add_argument(
        "--member-user-id",
        required=True,
        action="append",
        help="Member user id to invite (repeatable, required)",
    )
    gw_room_invite.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_room_remove = subparsers.add_parser("gw-room-remove", help="Remove members from a room via the gateway")
    gw_room_remove.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_room_remove.add_argument(
        "--member-user-id",
        required=True,
        action="append",
        help="Member user id to remove (repeatable, required)",
    )
    gw_room_remove.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_room_promote = subparsers.add_parser("gw-room-promote", help="Promote members in a room via the gateway")
    gw_room_promote.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_room_promote.add_argument(
        "--member-user-id",
        required=True,
        action="append",
        help="Member user id to promote (repeatable, required)",
    )
    gw_room_promote.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_room_demote = subparsers.add_parser("gw-room-demote", help="Demote members in a room via the gateway")
    gw_room_demote.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_room_demote.add_argument(
        "--member-user-id",
        required=True,
        action="append",
        help="Member user id to demote (repeatable, required)",
    )
    gw_room_demote.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_dm_init = subparsers.add_parser("gw-dm-init-send", help="Init a DM and send Welcome/Commit via gateway")
    gw_dm_init.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_dm_init.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_dm_init.add_argument("--peer-kp-b64", required=True, help="Peer KeyPackage (base64, required)")
    gw_dm_init.add_argument("--group-id", required=True, help="Group id (base64, required)")
    gw_dm_init.add_argument("--seed", type=int, default=7331, help="Deterministic seed (default: 7331)")
    gw_dm_init.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_room_init = subparsers.add_parser(
        "gw-room-init-send",
        help="Init a room via harness and send Welcome/Commit via gateway",
    )
    gw_room_init.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_room_init.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_room_init.add_argument(
        "--peer-kp-b64",
        required=True,
        action="append",
        help="Peer KeyPackage (base64, repeatable, required)",
    )
    gw_room_init.add_argument("--group-id", required=True, help="Group id (base64, required)")
    gw_room_init.add_argument("--seed", type=int, default=9001, help="Deterministic seed (default: 9001)")
    gw_room_init.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_room_add = subparsers.add_parser(
        "gw-room-add-send",
        help="Add peers via harness and send Welcome/Commit via gateway",
    )
    gw_room_add.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_room_add.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_room_add.add_argument(
        "--peer-kp-b64",
        required=True,
        action="append",
        help="Peer KeyPackage (base64, repeatable, required)",
    )
    gw_room_add.add_argument("--seed", type=int, default=9002, help="Deterministic seed (default: 9002)")
    gw_room_add.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_dm_send = subparsers.add_parser("gw-dm-send", help="Encrypt and send a DM application message")
    gw_dm_send.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_dm_send.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_dm_send.add_argument("--plaintext", required=True, help="Plaintext message (required)")
    gw_dm_send.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_phase5_room_smoke = subparsers.add_parser(
        "gw-phase5-room-smoke",
        help="Phase 5 interop smoke for room setup and envelope send",
    )
    gw_phase5_room_smoke.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_phase5_room_smoke.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")
    gw_phase5_room_smoke.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_phase5_room_smoke.add_argument(
        "--peer-user-id",
        required=True,
        action="append",
        help="Peer user id that must publish KeyPackages (repeatable, required)",
    )
    gw_phase5_room_smoke.add_argument(
        "--group-id-b64",
        default=_default_room_group_id_b64(),
        help='Group id (base64, default: base64("room-group"))',
    )
    gw_phase5_room_smoke.add_argument(
        "--kp-poll-seconds",
        type=int,
        default=30,
        help="Seconds to poll for KeyPackages (default: 30)",
    )
    gw_phase5_room_smoke.add_argument(
        "--kp-poll-interval-ms",
        type=int,
        default=500,
        help="Poll interval in milliseconds (default: 500)",
    )
    gw_phase5_room_smoke.add_argument(
        "--seed-keypackage",
        type=int,
        default=31001,
        help="Seed for dm-keypackage if initiator state is missing (default: 31001)",
    )
    gw_phase5_room_smoke.add_argument(
        "--seed-group-init",
        type=int,
        default=42001,
        help="Seed for group-init (default: 42001)",
    )
    gw_phase5_room_smoke.add_argument(
        "--seed-app",
        type=int,
        default=43001,
        help="Seed for app message planning (default: 43001)",
    )
    gw_phase5_room_smoke.add_argument(
        "--add-peer-user-id",
        action="append",
        help="Additional peer user id to add (repeatable)",
    )
    gw_phase5_room_smoke.add_argument(
        "--seed-group-add",
        type=int,
        default=52001,
        help="Seed for group-add (default: 52001)",
    )
    gw_phase5_room_smoke.add_argument(
        "--seed-app2",
        type=int,
        default=53001,
        help="Seed for second app message planning (default: 53001)",
    )
    gw_phase5_room_smoke.add_argument(
        "--plaintext2",
        default="phase5-room-smoke-2",
        help='Plaintext for the second app message (default: "phase5-room-smoke-2")',
    )
    gw_phase5_room_smoke.add_argument(
        "--transcript-out",
        help="Write a transcript JSON compatible with the web importer to this path",
    )
    gw_phase5_room_smoke.add_argument(
        "--print-web-cli-block",
        action="store_true",
        help="Print key=value lines for the web Parse CLI block helper",
    )
    gw_phase5_room_smoke.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a deterministic JSON plan without contacting the network",
    )

    gw_phase5_dm_proof = subparsers.add_parser(
        "gw-phase5-dm-proof",
        help="Phase 5 DM proof run with local gateway + web CSP server",
    )
    gw_phase5_dm_proof.add_argument(
        "--conv-id",
        default="phase5-dm-proof",
        help="Conversation id (default: phase5-dm-proof)",
    )
    gw_phase5_dm_proof.add_argument(
        "--group-id-b64",
        default=_default_dm_group_id_b64(),
        help='Group id (base64, default: base64("dm-group"))',
    )
    gw_phase5_dm_proof.add_argument(
        "--cli-auth-token",
        default="cli",
        help='CLI auth token (default: "cli")',
    )
    gw_phase5_dm_proof.add_argument(
        "--cli-device-id",
        default="cli_d1",
        help='CLI device id (default: "cli_d1")',
    )
    gw_phase5_dm_proof.add_argument(
        "--cli-user-id",
        default="cli",
        help='CLI user id (default: "cli")',
    )
    gw_phase5_dm_proof.add_argument(
        "--web-auth-token",
        default="web",
        help='Web auth token (default: "web")',
    )
    gw_phase5_dm_proof.add_argument(
        "--web-device-id",
        default="web_d1",
        help='Web device id (default: "web_d1")',
    )
    gw_phase5_dm_proof.add_argument(
        "--web-user-id",
        default="web",
        help='Web user id (default: "web")',
    )
    gw_phase5_dm_proof.add_argument(
        "--kp-poll-seconds",
        type=int,
        default=60,
        help="Seconds to poll for web KeyPackages (default: 60)",
    )
    gw_phase5_dm_proof.add_argument(
        "--kp-poll-interval-ms",
        type=int,
        default=500,
        help="Poll interval in milliseconds (default: 500)",
    )
    gw_phase5_dm_proof.add_argument(
        "--seed-keypackage",
        type=int,
        default=71001,
        help="Seed for dm-keypackage if initiator state is missing (default: 71001)",
    )
    gw_phase5_dm_proof.add_argument(
        "--seed-dm-init",
        type=int,
        default=72001,
        help="Seed for dm-init (default: 72001)",
    )
    gw_phase5_dm_proof.add_argument(
        "--plaintext",
        default="phase5-dm-proof",
        help='Plaintext for the app message (default: "phase5-dm-proof")',
    )
    gw_phase5_dm_proof.add_argument(
        "--send-peer-token",
        help="Optional plaintext for a second app message sent after the proof app message",
    )
    gw_phase5_dm_proof.add_argument(
        "--wait-peer-app",
        action="store_true",
        help="Wait for a peer app message and decrypt it",
    )
    gw_phase5_dm_proof.add_argument(
        "--peer-app-expected",
        help="Expected peer app plaintext (optional; requires --wait-peer-app)",
    )
    gw_phase5_dm_proof.add_argument(
        "--peer-app-timeout-s",
        type=float,
        default=90.0,
        help="Seconds to wait for peer app message (default: 90)",
    )
    gw_phase5_dm_proof.add_argument(
        "--peer-app-idle-timeout-s",
        type=float,
        default=2.5,
        help="SSE idle timeout while waiting for peer app (default: 2.5)",
    )
    gw_phase5_dm_proof.add_argument(
        "--gateway-ready-timeout-s",
        type=float,
        default=10.0,
        help="Seconds to wait for gateway /healthz (default: 10)",
    )

    gw_phase5_room_proof = subparsers.add_parser(
        "gw-phase5-room-proof",
        help="Phase 5 proof run with local gateway + web CSP server",
    )
    gw_phase5_room_proof.add_argument(
        "--conv-id",
        default="phase5-room-proof",
        help="Conversation id (default: phase5-room-proof)",
    )
    gw_phase5_room_proof.add_argument(
        "--group-id-b64",
        default=_default_room_group_id_b64(),
        help='Group id (base64, default: base64("room-group"))',
    )
    gw_phase5_room_proof.add_argument(
        "--cli-auth-token",
        default="cli",
        help='CLI auth token (default: "cli")',
    )
    gw_phase5_room_proof.add_argument(
        "--cli-device-id",
        default="cli_d1",
        help='CLI device id (default: "cli_d1")',
    )
    gw_phase5_room_proof.add_argument(
        "--cli-user-id",
        default="cli",
        help='CLI user id (default: "cli")',
    )
    gw_phase5_room_proof.add_argument(
        "--web-auth-token",
        default="web",
        help='Web auth token (default: "web")',
    )
    gw_phase5_room_proof.add_argument(
        "--web-device-id",
        default="web_d1",
        help='Web device id (default: "web_d1")',
    )
    gw_phase5_room_proof.add_argument(
        "--web-user-id",
        default="web",
        help='Web user id (default: "web")',
    )
    gw_phase5_room_proof.add_argument(
        "--kp-poll-seconds",
        type=int,
        default=60,
        help="Seconds to poll for web KeyPackages (default: 60)",
    )
    gw_phase5_room_proof.add_argument(
        "--kp-poll-interval-ms",
        type=int,
        default=500,
        help="Poll interval in milliseconds (default: 500)",
    )
    gw_phase5_room_proof.add_argument(
        "--seed-keypackage",
        type=int,
        default=61001,
        help="Seed for dm-keypackage if initiator state is missing (default: 61001)",
    )
    gw_phase5_room_proof.add_argument(
        "--seed-group-init",
        type=int,
        default=62001,
        help="Seed for group-init (default: 62001)",
    )
    gw_phase5_room_proof.add_argument(
        "--plaintext",
        default="phase5-room-proof",
        help='Plaintext for the app message (default: "phase5-room-proof")',
    )
    gw_phase5_room_proof.add_argument(
        "--send-peer-token",
        help="Optional plaintext for a second app message sent after the proof app message",
    )
    gw_phase5_room_proof.add_argument(
        "--wait-peer-app",
        action="store_true",
        help="Wait for a peer app message and decrypt it",
    )
    gw_phase5_room_proof.add_argument(
        "--peer-app-expected",
        help="Expected peer app plaintext (optional; requires --wait-peer-app)",
    )
    gw_phase5_room_proof.add_argument(
        "--peer-app-timeout-s",
        type=float,
        default=90.0,
        help="Seconds to wait for peer app message (default: 90)",
    )
    gw_phase5_room_proof.add_argument(
        "--peer-app-idle-timeout-s",
        type=float,
        default=2.5,
        help="SSE idle timeout while waiting for peer app (default: 2.5)",
    )
    gw_phase5_room_proof.add_argument(
        "--gateway-ready-timeout-s",
        type=float,
        default=10.0,
        help="Seconds to wait for gateway /healthz (default: 10)",
    )

    gw_phase5_coexist_proof = subparsers.add_parser(
        "gw-phase5-coexist-proof",
        help="Phase 5 co-existence proof (DM + room) in one local gateway session",
    )
    gw_phase5_coexist_proof.add_argument(
        "--dm-conv-id",
        default="phase5-dm-proof",
        help="DM conversation id (default: phase5-dm-proof)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--room-conv-id",
        default="phase5-room-proof",
        help="Room conversation id (default: phase5-room-proof)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--dm-group-id-b64",
        default=_default_dm_group_id_b64(),
        help='DM group id (base64, default: base64("dm-group"))',
    )
    gw_phase5_coexist_proof.add_argument(
        "--room-group-id-b64",
        default=_default_room_group_id_b64(),
        help='Room group id (base64, default: base64("room-group"))',
    )
    gw_phase5_coexist_proof.add_argument(
        "--cli-auth-token",
        default="cli",
        help='CLI auth token (default: "cli")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--cli-device-id",
        default="cli_d1",
        help='CLI device id (default: "cli_d1")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--cli-user-id",
        default="cli",
        help='CLI user id (default: "cli")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--web-auth-token",
        default="web",
        help='Web auth token (default: "web")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--web-device-id",
        default="web_d1",
        help='Web device id (default: "web_d1")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--web-user-id",
        default="web",
        help='Web user id (default: "web")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--kp-poll-seconds",
        type=int,
        default=60,
        help="Seconds to poll for web KeyPackages (default: 60)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--kp-poll-interval-ms",
        type=int,
        default=500,
        help="Poll interval in milliseconds (default: 500)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--seed-keypackage",
        type=int,
        default=71001,
        help="Seed for dm-keypackage if initiator state is missing (default: 71001)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--seed-dm-init",
        type=int,
        default=72001,
        help="Seed for dm-init (default: 72001)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--seed-group-init",
        type=int,
        default=62001,
        help="Seed for group-init (default: 62001)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--dm-plaintext",
        default="phase5-dm-proof",
        help='Plaintext for the DM app message (default: "phase5-dm-proof")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--room-plaintext",
        default="phase5-room-proof",
        help='Plaintext for the room app message (default: "phase5-room-proof")',
    )
    gw_phase5_coexist_proof.add_argument(
        "--send-peer-token",
        help="Optional plaintext for a second app message sent after each proof app message",
    )
    gw_phase5_coexist_proof.add_argument(
        "--auto-reply-hint",
        help="Optional hint to print for enabling auto-reply in the web UI",
    )
    gw_phase5_coexist_proof.add_argument(
        "--wait-peer-app",
        action="store_true",
        help="Wait for peer app messages for both DM and room, then decrypt",
    )
    gw_phase5_coexist_proof.add_argument(
        "--peer-app-expected",
        help="Expected peer app plaintext (optional; requires --wait-peer-app)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--peer-app-timeout-s",
        type=float,
        default=90.0,
        help="Seconds to wait for peer app message (default: 90)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--peer-app-idle-timeout-s",
        type=float,
        default=2.5,
        help="SSE idle timeout while waiting for peer app (default: 2.5)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--gateway-ready-timeout-s",
        type=float,
        default=10.0,
        help="Seconds to wait for gateway /healthz (default: 10)",
    )
    gw_phase5_coexist_proof.add_argument(
        "--dm-transcript-out",
        help="Write the DM transcript JSON to this path",
    )
    gw_phase5_coexist_proof.add_argument(
        "--room-transcript-out",
        help="Write the room transcript JSON to this path",
    )
    gw_phase5_coexist_proof.add_argument(
        "--coexist-bundle-out",
        help="Write the combined coexist bundle JSON to this path",
    )
    gw_phase5_coexist_proof.add_argument(
        "--print-web-cli-block",
        action="store_true",
        help="Print key=value lines for the web Parse CLI block helper (DM + room)",
    )

    gw_dm_tail = subparsers.add_parser("gw-dm-tail", help="Tail and apply DM gateway events")
    gw_dm_tail.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_dm_tail.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_dm_tail.add_argument("--from-seq", type=int, help="Sequence to replay from (defaults to stored cursor)")
    gw_dm_tail.add_argument("--max-events", type=int, help="Stop after emitting this many events")
    gw_dm_tail.add_argument(
        "--idle-timeout-s",
        type=float,
        nargs="?",
        const=5.0,
        default=None,
        help="Stop if idle for this many seconds (default: none; if flag present defaults to 5.0)",
    )
    gw_dm_tail.add_argument(
        "--wipe-state",
        action="store_true",
        help="Delete state_dir before replaying events (requires --from-seq, recommended 1)",
    )
    gw_dm_tail.add_argument("--ack", action=argparse.BooleanOptionalAction, default=True, help="Ack events (default)")
    gw_dm_tail.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    dm_keypackage = subparsers.add_parser("dm-keypackage", help="Generate a DM KeyPackage")
    dm_keypackage.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    dm_keypackage.add_argument("--name", required=True, help="Participant name (required)")
    dm_keypackage.add_argument("--seed", required=True, type=int, help="Deterministic RNG seed (required)")

    dm_init = subparsers.add_parser("dm-init", help="Initialize a DM group and emit Welcome/Commit")
    dm_init.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    dm_init.add_argument("--peer-keypackage", required=True, help="Peer KeyPackage (base64, required)")
    dm_init.add_argument("--group-id", required=True, help="MLS group id (base64, required)")
    dm_init.add_argument("--seed", required=True, type=int, help="Deterministic RNG seed (required)")

    dm_join = subparsers.add_parser("dm-join", help="Join a DM group using a Welcome")
    dm_join.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    dm_join.add_argument("--welcome", required=True, help="Welcome message (base64, required)")

    dm_commit_apply = subparsers.add_parser("dm-commit-apply", help="Apply a DM commit")
    dm_commit_apply.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    dm_commit_apply.add_argument("--commit", required=True, help="Commit message (base64, required)")

    dm_encrypt = subparsers.add_parser("dm-encrypt", help="Encrypt a DM plaintext message")
    dm_encrypt.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    dm_encrypt.add_argument("--plaintext", required=True, help="Plaintext message (required)")

    dm_decrypt = subparsers.add_parser("dm-decrypt", help="Decrypt a DM ciphertext message")
    dm_decrypt.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    dm_decrypt.add_argument("--ciphertext", required=True, help="Ciphertext message (base64, required)")

    return parser


def handle_vectors(args: argparse.Namespace) -> int:
    return run_harness("vectors", ["--vector-file", args.vector_file])


def handle_smoke(args: argparse.Namespace) -> int:
    return run_harness(
        "smoke",
        [
            "--iterations",
            str(args.iterations),
            "--save-every",
            str(args.save_every),
            "--state-dir",
            args.state_dir,
        ],
    )


def handle_soak(args: argparse.Namespace) -> int:
    return run_harness(
        "soak",
        [
            "--iterations",
            str(args.iterations),
            "--save-every",
            str(args.save_every),
            "--state-dir",
            args.state_dir,
        ],
    )


def handle_whoami(args: argparse.Namespace) -> int:
    path = Path(args.identity_file) if args.identity_file else args.profile_paths.identity_path
    identity = identity_store.load_or_create_identity(path)
    auth_body = identity.auth_token
    if identity.auth_token.startswith("Bearer "):
        suffix = identity.auth_token[len("Bearer ") :]
        auth_body = f"Bearer {suffix[:8]}..." if len(suffix) > 8 else identity.auth_token

    sys.stdout.write(f"user_id: {identity.user_id}\n")
    sys.stdout.write(f"auth_token: {auth_body}\n")
    sys.stdout.write(f"device_id: {identity.device_id}\n")
    sys.stdout.write(f"identity_file: {path.expanduser()}\n")
    return 0


def _load_session(base_url: str | None, session_path: Path) -> tuple[str, str]:
    stored = gateway_store.load_session(session_path)
    if stored is None:
        raise RuntimeError("No stored gateway session. Run gw-start or gw-resume first.")

    resolved_base_url = base_url or stored["base_url"]
    return resolved_base_url, stored["session_token"]


def handle_gw_start(args: argparse.Namespace) -> int:
    identity = identity_store.load_or_create_identity(args.profile_paths.identity_path)
    response = gateway_client.session_start(
        args.base_url,
        identity.auth_token,
        identity.device_id,
        identity.device_credential,
    )
    gateway_store.save_session(
        args.base_url,
        response["session_token"],
        response["resume_token"],
        args.profile_paths.session_path,
    )
    sys.stdout.write("Gateway session started.\n")
    return 0


def handle_gw_resume(args: argparse.Namespace) -> int:
    stored = gateway_store.load_session(args.profile_paths.session_path)
    if stored is None:
        raise RuntimeError("No stored gateway session. Run gw-start first.")
    response = gateway_client.session_resume(args.base_url, stored["resume_token"])
    gateway_store.save_session(
        args.base_url,
        response["session_token"],
        response["resume_token"],
        args.profile_paths.session_path,
    )
    sys.stdout.write("Gateway session resumed.\n")
    return 0


def handle_gw_send(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.inbox_send(
        base_url,
        session_token,
        args.conv_id,
        args.msg_id,
        args.env_b64,
    )
    sys.stdout.write(f"seq: {response['seq']}\n")
    return 0


def handle_gw_ack(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    gateway_client.inbox_ack(base_url, session_token, args.conv_id, args.seq)
    next_seq = gateway_store.update_next_seq(args.conv_id, args.seq, args.profile_paths.cursors_path)
    sys.stdout.write(f"next_seq: {next_seq}\n")
    return 0


def handle_gw_tail(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    from_seq = (
        args.from_seq
        if args.from_seq is not None
        else gateway_store.get_next_seq(args.conv_id, args.profile_paths.cursors_path)
    )
    for event in gateway_client.sse_tail(
        base_url,
        session_token,
        args.conv_id,
        from_seq,
        max_events=args.max_events,
        idle_timeout_s=args.idle_timeout_s,
    ):
        sys.stdout.write(f"{json.dumps(event, sort_keys=True)}\n")
    return 0


def handle_gw_kp_publish(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    identity = identity_store.load_or_create_identity(args.profile_paths.identity_path)
    keypackages: list[str] = []
    for offset in range(args.count):
        output = _run_harness_capture(
            "dm-keypackage",
            [
                "--state-dir",
                args.state_dir,
                "--name",
                args.name,
                "--seed",
                str(args.seed_base + offset),
            ],
        )
        keypackages.append(_first_nonempty_line(output))
    response = gateway_client.keypackages_publish(
        base_url,
        session_token,
        identity.device_id,
        keypackages,
    )
    sys.stdout.write(f"{json.dumps(response, sort_keys=True)}\n")
    return 0


def handle_gw_kp_fetch(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.keypackages_fetch(base_url, session_token, args.user_id, args.count)
    keypackages = response.get("keypackages", [])
    if not keypackages and not args.allow_empty:
        sys.stderr.write(f"No KeyPackages available for user {args.user_id}.\n")
        return 1
    for keypackage in keypackages:
        sys.stdout.write(f"{keypackage}\n")
    return 0


def handle_gw_dm_create(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.room_create(base_url, session_token, args.conv_id, [args.peer_user_id])
    sys.stdout.write(f"{json.dumps(response, sort_keys=True)}\n")
    return 0


def handle_gw_room_create(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.room_create(base_url, session_token, args.conv_id, args.member_user_id)
    sys.stdout.write(f"{json.dumps(response, sort_keys=True)}\n")
    return 0


def handle_gw_room_invite(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.room_invite(base_url, session_token, args.conv_id, args.member_user_id)
    sys.stdout.write(f"{json.dumps(response, sort_keys=True)}\n")
    return 0


def handle_gw_room_remove(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.room_remove(base_url, session_token, args.conv_id, args.member_user_id)
    sys.stdout.write(f"{json.dumps(response, sort_keys=True)}\n")
    return 0


def handle_gw_room_promote(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.room_promote(base_url, session_token, args.conv_id, args.member_user_id)
    sys.stdout.write(f"{json.dumps(response, sort_keys=True)}\n")
    return 0


def handle_gw_room_demote(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    response = gateway_client.room_demote(base_url, session_token, args.conv_id, args.member_user_id)
    sys.stdout.write(f"{json.dumps(response, sort_keys=True)}\n")
    return 0


def handle_gw_dm_init_send(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    output = _run_harness_capture(
        "dm-init",
        [
            "--state-dir",
            args.state_dir,
            "--peer-keypackage",
            args.peer_kp_b64,
            "--group-id",
            args.group_id,
            "--seed",
            str(args.seed),
        ],
    )
    payload = json.loads(_first_nonempty_line(output))
    welcome = str(payload["welcome"])
    commit = str(payload["commit"])

    welcome_env = dm_envelope.pack(0x01, welcome)
    welcome_msg_id = _msg_id_for_env(welcome_env)
    welcome_response = gateway_client.inbox_send(
        base_url,
        session_token,
        args.conv_id,
        welcome_msg_id,
        welcome_env,
    )
    sys.stdout.write(f"welcome_seq: {welcome_response['seq']}\n")

    commit_env = dm_envelope.pack(0x02, commit)
    commit_msg_id = _msg_id_for_env(commit_env)
    commit_response = gateway_client.inbox_send(
        base_url,
        session_token,
        args.conv_id,
        commit_msg_id,
        commit_env,
    )
    sys.stdout.write(f"commit_seq: {commit_response['seq']}\n")
    return 0


def _peer_keypackage_args(peer_kp_b64: Iterable[str]) -> list[str]:
    args: list[str] = []
    for keypackage in peer_kp_b64:
        args.extend(["--peer-keypackage", keypackage])
    return args


def _send_welcome_commit(
    base_url: str,
    session_token: str,
    conv_id: str,
    payload: dict[str, object],
) -> None:
    welcome = str(payload["welcome"])
    commit = str(payload["commit"])

    welcome_env = dm_envelope.pack(0x01, welcome)
    welcome_msg_id = _msg_id_for_env(welcome_env)
    welcome_response = gateway_client.inbox_send(
        base_url,
        session_token,
        conv_id,
        welcome_msg_id,
        welcome_env,
    )
    sys.stdout.write(f"welcome_seq: {welcome_response['seq']}\n")

    commit_env = dm_envelope.pack(0x02, commit)
    commit_msg_id = _msg_id_for_env(commit_env)
    commit_response = gateway_client.inbox_send(
        base_url,
        session_token,
        conv_id,
        commit_msg_id,
        commit_env,
    )
    sys.stdout.write(f"commit_seq: {commit_response['seq']}\n")


def _extract_proposals(payload: dict[str, object]) -> list[str]:
    proposals = payload.get("proposals")
    if not isinstance(proposals, list):
        return []
    return [proposal for proposal in proposals if isinstance(proposal, str)]


def _send_proposals(
    base_url: str,
    session_token: str,
    conv_id: str,
    proposals: Iterable[str],
) -> list[int]:
    proposal_seqs: list[int] = []
    for proposal in proposals:
        proposal_env = dm_envelope.pack(0x02, proposal)
        proposal_seqs.append(_send_envelope(base_url, session_token, conv_id, proposal_env))
    return proposal_seqs


def _append_transcript_event(events: list[dict[str, object]], seq: int, env: str) -> None:
    events.append({"seq": seq, "env": env, "msg_id": _msg_id_for_env(env)})


def _send_proposals_with_events(
    base_url: str,
    session_token: str,
    conv_id: str,
    proposals: Iterable[str],
    events: list[dict[str, object]],
) -> list[int]:
    proposal_seqs: list[int] = []
    for proposal in proposals:
        proposal_env = dm_envelope.pack(0x02, proposal)
        proposal_seq = _send_envelope(base_url, session_token, conv_id, proposal_env)
        proposal_seqs.append(proposal_seq)
        _append_transcript_event(events, proposal_seq, proposal_env)
    return proposal_seqs


def _build_transcript_payload(conv_id: str, events: Iterable[dict[str, object]]) -> dict[str, object]:
    normalized_events: list[dict[str, object]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        seq = event.get("seq")
        env = event.get("env")
        if not isinstance(seq, int) or not isinstance(env, str):
            continue
        msg_id = event.get("msg_id")
        if not isinstance(msg_id, str):
            msg_id = _msg_id_for_env(env)
        normalized_events.append({"seq": seq, "env": env, "msg_id": msg_id})
    canonical = interop_transcript.canonicalize_transcript(conv_id, 1, None, normalized_events)
    seqs = [entry["seq"] for entry in canonical["events"] if isinstance(entry.get("seq"), int)]
    canonical["next_seq"] = max(seqs) + 1 if seqs else 1
    digest = interop_transcript.compute_digest_sha256_b64(canonical)
    payload = dict(canonical)
    payload["digest_sha256_b64"] = digest
    return payload


def _emit_web_cli_block(
    *,
    conv_id: str | None,
    welcome_env: str | None,
    commit_env: str | None,
    app_env: str | None,
    expected_plaintext: str,
) -> None:
    lines: list[str] = []
    if conv_id:
        lines.append(f"conv_id={conv_id}")
    if welcome_env:
        lines.append(f"welcome_env_b64={welcome_env}")
    if commit_env:
        lines.append(f"commit_env_b64={commit_env}")
    if app_env:
        lines.append(f"app_env_b64={app_env}")
    if expected_plaintext:
        lines.append(f"expected_plaintext={expected_plaintext}")
    if lines:
        sys.stdout.write("\n".join(lines) + "\n")


def _reserve_local_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _start_daemon_process(
    *,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None,
    log_path: Path,
) -> tuple[subprocess.Popen[bytes], IO[str]]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return process, log_file


def _read_log_excerpt(log_file: IO[str], max_bytes: int = 4000) -> str:
    log_file.flush()
    log_file.seek(0, os.SEEK_END)
    end = log_file.tell()
    if end == 0:
        return ""
    to_read = min(max_bytes, end)
    log_file.seek(-to_read, os.SEEK_END)
    return log_file.read()


def _poll_gateway_health(
    *,
    base_url: str,
    timeout_s: float,
    interval_s: float,
    process: subprocess.Popen[bytes],
    log_file: IO[str],
) -> None:
    deadline = time.time() + timeout_s
    health_url = f"{base_url.rstrip('/')}/healthz"
    while True:
        if process.poll() is not None:
            details = _read_log_excerpt(log_file)
            message = f"Gateway exited early with code {process.returncode}."
            if details:
                message += f"\nGateway output:\n{details}"
            raise RuntimeError(message)
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                body = response.read().decode("utf-8").strip()
            if response.status == 200 and body == "ok":
                return
        except urllib.error.URLError:
            pass
        if time.time() >= deadline:
            details = _read_log_excerpt(log_file)
            message = "Gateway did not become healthy in time."
            if details:
                message += f"\nGateway output:\n{details}"
            raise RuntimeError(message)
        time.sleep(interval_s)


def _emit_phase5_web_instructions(
    *,
    web_url: str,
    gateway_url: str,
    web_auth_token: str,
    web_device_id: str,
) -> None:
    sys.stdout.write("Phase 5 web steps:\n")
    sys.stdout.write(f"  1) Open: {web_url}\n")
    sys.stdout.write(f"  2) Set gateway_url to: {gateway_url}\n")
    sys.stdout.write(f"  3) Start session with auth_token={web_auth_token} device_id={web_device_id}\n")
    sys.stdout.write("  4) Publish 1 KeyPackage from the web UI.\n")


def _wait_for_peer_app(
    *,
    base_url: str,
    session_token: str,
    conv_id: str,
    from_seq: int,
    state_dir: str,
    timeout_s: float,
    idle_timeout_s: float,
) -> str:
    deadline = time.time() + timeout_s
    next_seq = from_seq
    while time.time() < deadline:
        for event in gateway_client.sse_tail(
            base_url,
            session_token,
            conv_id,
            next_seq,
            idle_timeout_s=idle_timeout_s,
        ):
            body = event.get("body", {})
            seq = body.get("seq")
            env_b64 = body.get("env")
            if not isinstance(seq, int) or not isinstance(env_b64, str):
                continue
            next_seq = seq + 1
            kind, payload_b64 = dm_envelope.unpack(env_b64)
            if kind == 0x03:
                output = _run_harness_capture(
                    "dm-decrypt",
                    [
                        "--state-dir",
                        state_dir,
                        "--ciphertext",
                        payload_b64,
                    ],
                )
                return _first_nonempty_line(output)
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for peer app message")


def _start_phase5_services(
    *,
    repo_root: Path,
    temp_root: Path,
    gateway_ready_timeout_s: float,
) -> dict[str, object]:
    gateway_log = temp_root / "logs" / "gateway.log"
    web_log = temp_root / "logs" / "web.log"
    gateway_db = temp_root / "gateway.sqlite"

    gateway_port = _reserve_local_port()
    web_port = _reserve_local_port()
    gateway_url = f"http://127.0.0.1:{gateway_port}"
    web_url = f"http://127.0.0.1:{web_port}"

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(repo_root / "gateway" / "src"))

    gateway_cmd = [
        sys.executable,
        "-m",
        "gateway.server",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(gateway_port),
        "--db",
        str(gateway_db),
    ]
    web_cmd = [
        sys.executable,
        str(repo_root / "clients" / "web" / "tools" / "csp_dev_server.py"),
        "--serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(web_port),
        "--build-wasm-if-missing",
    ]

    gateway_process, gateway_log_file = _start_daemon_process(
        cmd=gateway_cmd,
        cwd=repo_root,
        env=env,
        log_path=gateway_log,
    )
    _poll_gateway_health(
        base_url=gateway_url,
        timeout_s=gateway_ready_timeout_s,
        interval_s=0.25,
        process=gateway_process,
        log_file=gateway_log_file,
    )
    web_process, web_log_file = _start_daemon_process(
        cmd=web_cmd,
        cwd=repo_root,
        env=None,
        log_path=web_log,
    )

    return {
        "gateway_db": gateway_db,
        "gateway_log": gateway_log,
        "web_log": web_log,
        "gateway_url": gateway_url,
        "web_url": web_url,
        "gateway_process": gateway_process,
        "web_process": web_process,
        "gateway_log_file": gateway_log_file,
        "web_log_file": web_log_file,
    }


def _phase5_proof_step(
    *,
    base_url: str,
    session_token: str,
    conv_id: str,
    group_id_b64: str,
    cli_state_dir: str,
    cli_user_id: str,
    web_user_id: str,
    kp_poll_seconds: int,
    kp_poll_interval_ms: int,
    seed_keypackage: int,
    seed_init: int,
    plaintext: str,
    send_peer_token: str | None,
    wait_peer_app: bool,
    peer_app_expected: str | None,
    peer_app_timeout_s: float,
    peer_app_idle_timeout_s: float,
    init_command: str,
    command_label: str,
    transcript_path: Path,
    print_web_cli_block: bool,
    web_cli_header: str | None,
) -> dict[str, object]:
    transcript_events: list[dict[str, object]] = []

    _ensure_initiator_state(cli_state_dir, seed_keypackage)
    web_keypackage = _poll_keypackage(
        base_url,
        session_token,
        web_user_id,
        kp_poll_seconds,
        kp_poll_interval_ms,
    )
    gateway_client.room_create(
        base_url,
        session_token,
        conv_id,
        [cli_user_id, web_user_id],
    )

    output = _run_harness_capture(
        init_command,
        [
            "--state-dir",
            cli_state_dir,
            "--peer-keypackage",
            web_keypackage,
            "--group-id",
            group_id_b64,
            "--seed",
            str(seed_init),
        ],
    )
    payload = json.loads(_first_nonempty_line(output))
    welcome_env = dm_envelope.pack(0x01, str(payload["welcome"]))

    welcome_seq = _send_envelope(base_url, session_token, conv_id, welcome_env)
    _append_transcript_event(transcript_events, welcome_seq, welcome_env)

    proposals = _extract_proposals(payload)
    proposal_seqs = _send_proposals_with_events(
        base_url,
        session_token,
        conv_id,
        proposals,
        transcript_events,
    )

    commit_env = None
    commit_seq = None
    if "commit" in payload:
        commit_env = dm_envelope.pack(0x02, str(payload["commit"]))
        commit_seq = _send_envelope(base_url, session_token, conv_id, commit_env)
        _append_transcript_event(transcript_events, commit_seq, commit_env)

    app_output = _run_harness_capture(
        "dm-encrypt",
        [
            "--state-dir",
            cli_state_dir,
            "--plaintext",
            plaintext,
        ],
    )
    app_ciphertext = _first_nonempty_line(app_output)
    app_env = dm_envelope.pack(0x03, app_ciphertext)
    app_seq = _send_envelope(base_url, session_token, conv_id, app_env)
    _append_transcript_event(transcript_events, app_seq, app_env)

    sent_peer_token_seq = None
    if send_peer_token:
        token_output = _run_harness_capture(
            "dm-encrypt",
            [
                "--state-dir",
                cli_state_dir,
                "--plaintext",
                send_peer_token,
            ],
        )
        token_ciphertext = _first_nonempty_line(token_output)
        token_env = dm_envelope.pack(0x03, token_ciphertext)
        sent_peer_token_seq = _send_envelope(base_url, session_token, conv_id, token_env)
        _append_transcript_event(transcript_events, sent_peer_token_seq, token_env)

    transcript_payload = _build_transcript_payload(conv_id, transcript_events)
    _atomic_write_json(transcript_path, transcript_payload)

    if print_web_cli_block:
        if web_cli_header:
            sys.stdout.write(f"{web_cli_header}\n")
        _emit_web_cli_block(
            conv_id=conv_id,
            welcome_env=welcome_env,
            commit_env=commit_env,
            app_env=app_env,
            expected_plaintext=plaintext,
        )

    peer_app_plaintext = None
    if wait_peer_app:
        sys.stdout.write("Waiting for peer app message...\n")
        from_seq = (sent_peer_token_seq if sent_peer_token_seq is not None else app_seq) + 1
        peer_app_plaintext = _wait_for_peer_app(
            base_url=base_url,
            session_token=session_token,
            conv_id=conv_id,
            from_seq=from_seq,
            state_dir=cli_state_dir,
            timeout_s=peer_app_timeout_s,
            idle_timeout_s=peer_app_idle_timeout_s,
        )
        sys.stdout.write(f"peer_app_plaintext: {peer_app_plaintext}\n")

    handshake_candidates = list(proposal_seqs)
    if commit_seq is not None:
        handshake_candidates.append(commit_seq)
    if not handshake_candidates:
        handshake_candidates.append(welcome_seq)
    last_handshake_seq = max(handshake_candidates)

    summary: dict[str, object] = {
        "app_seq": app_seq,
        "command": command_label,
        "conv_id": conv_id,
        "digest_sha256_b64": transcript_payload.get("digest_sha256_b64"),
        "last_handshake_seq": last_handshake_seq,
        "sent_peer_token": bool(send_peer_token),
        "sent_peer_token_plaintext": send_peer_token or "",
        "sent_peer_token_seq": sent_peer_token_seq,
        "welcome_seq": welcome_seq,
    }
    if commit_seq is not None:
        summary["commit_seq"] = commit_seq
    if proposal_seqs:
        summary["proposal_seqs"] = proposal_seqs
    if peer_app_plaintext is not None:
        summary["peer_app_plaintext"] = peer_app_plaintext
        summary["peer_app_decrypted"] = True
    elif wait_peer_app:
        summary["peer_app_decrypted"] = False
    if peer_app_expected is not None:
        summary["peer_app_expected"] = peer_app_expected
        if peer_app_plaintext is not None:
            summary["peer_app_expected_match"] = peer_app_plaintext == peer_app_expected
        else:
            summary["peer_app_expected_match"] = False
    return summary


def _handle_gw_phase5_local_proof(
    *,
    conv_id: str,
    group_id_b64: str,
    cli_auth_token: str,
    cli_device_id: str,
    cli_user_id: str,
    web_auth_token: str,
    web_device_id: str,
    web_user_id: str,
    kp_poll_seconds: int,
    kp_poll_interval_ms: int,
    seed_keypackage: int,
    seed_init: int,
    plaintext: str,
    send_peer_token: str | None,
    wait_peer_app: bool,
    peer_app_expected: str | None,
    peer_app_timeout_s: float,
    peer_app_idle_timeout_s: float,
    gateway_ready_timeout_s: float,
    init_command: str,
    command_label: str,
    temp_prefix: str,
) -> int:
    repo_root = find_repo_root()
    temp_root = Path(tempfile.mkdtemp(prefix=temp_prefix))
    cli_state_dir = temp_root / "cli_state"
    transcript_path = temp_root / "phase5_transcript.json"

    gateway_process = None
    web_process = None
    gateway_log_file = None
    web_log_file = None
    gateway_log = None
    web_log = None
    try:
        services = _start_phase5_services(
            repo_root=repo_root,
            temp_root=temp_root,
            gateway_ready_timeout_s=gateway_ready_timeout_s,
        )
        gateway_process = services["gateway_process"]
        web_process = services["web_process"]
        gateway_log_file = services["gateway_log_file"]
        web_log_file = services["web_log_file"]
        gateway_url = services["gateway_url"]
        web_url = services["web_url"]
        gateway_log = services["gateway_log"]
        web_log = services["web_log"]

        sys.stdout.write(f"Gateway URL: {gateway_url}\n")
        sys.stdout.write(f"Web URL: {web_url}\n")
        sys.stdout.write(f"Transcript path: {transcript_path}\n")
        sys.stdout.write(f"Logs: {gateway_log} {web_log}\n")
        _emit_phase5_web_instructions(
            web_url=web_url,
            gateway_url=gateway_url,
            web_auth_token=web_auth_token,
            web_device_id=web_device_id,
        )

        session = gateway_client.session_start(
            gateway_url,
            cli_auth_token,
            cli_device_id,
        )
        session_token = session["session_token"]
        sys.stdout.write("Waiting for web KeyPackage...\n")

        sys.stdout.write("Web CLI block:\n")
        summary = _phase5_proof_step(
            base_url=gateway_url,
            session_token=session_token,
            conv_id=conv_id,
            group_id_b64=group_id_b64,
            cli_state_dir=str(cli_state_dir),
            cli_user_id=cli_user_id,
            web_user_id=web_user_id,
            kp_poll_seconds=kp_poll_seconds,
            kp_poll_interval_ms=kp_poll_interval_ms,
            seed_keypackage=seed_keypackage,
            seed_init=seed_init,
            plaintext=plaintext,
            send_peer_token=send_peer_token,
            wait_peer_app=wait_peer_app,
            peer_app_expected=peer_app_expected,
            peer_app_timeout_s=peer_app_timeout_s,
            peer_app_idle_timeout_s=peer_app_idle_timeout_s,
            init_command=init_command,
            command_label=command_label,
            transcript_path=transcript_path,
            print_web_cli_block=True,
            web_cli_header=None,
        )

        summary_output = {
            "app_seq": summary["app_seq"],
            "command": summary["command"],
            "conv_id": summary["conv_id"],
            "sent_peer_token": summary["sent_peer_token"],
            "sent_peer_token_plaintext": summary["sent_peer_token_plaintext"],
            "sent_peer_token_seq": summary["sent_peer_token_seq"],
            "welcome_seq": summary["welcome_seq"],
        }
        if "commit_seq" in summary:
            summary_output["commit_seq"] = summary["commit_seq"]
        if "proposal_seqs" in summary:
            summary_output["proposal_seqs"] = summary["proposal_seqs"]
        sys.stdout.write(f"{json.dumps(summary_output, sort_keys=True)}\n")
        return 0
    finally:
        for process in [web_process, gateway_process]:
            if process and process.poll() is None:
                process.terminate()
        for process in [web_process, gateway_process]:
            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        for log_file in [web_log_file, gateway_log_file]:
            if log_file:
                log_file.close()


def handle_gw_phase5_dm_proof(args: argparse.Namespace) -> int:
    return _handle_gw_phase5_local_proof(
        conv_id=args.conv_id,
        group_id_b64=args.group_id_b64,
        cli_auth_token=args.cli_auth_token,
        cli_device_id=args.cli_device_id,
        cli_user_id=args.cli_user_id,
        web_auth_token=args.web_auth_token,
        web_device_id=args.web_device_id,
        web_user_id=args.web_user_id,
        kp_poll_seconds=args.kp_poll_seconds,
        kp_poll_interval_ms=args.kp_poll_interval_ms,
        seed_keypackage=args.seed_keypackage,
        seed_init=args.seed_dm_init,
        plaintext=args.plaintext,
        send_peer_token=args.send_peer_token,
        wait_peer_app=args.wait_peer_app,
        peer_app_expected=args.peer_app_expected,
        peer_app_timeout_s=args.peer_app_timeout_s,
        peer_app_idle_timeout_s=args.peer_app_idle_timeout_s,
        gateway_ready_timeout_s=args.gateway_ready_timeout_s,
        init_command="dm-init",
        command_label="gw-phase5-dm-proof",
        temp_prefix="phase5-dm-proof-",
    )


def handle_gw_phase5_room_proof(args: argparse.Namespace) -> int:
    return _handle_gw_phase5_local_proof(
        conv_id=args.conv_id,
        group_id_b64=args.group_id_b64,
        cli_auth_token=args.cli_auth_token,
        cli_device_id=args.cli_device_id,
        cli_user_id=args.cli_user_id,
        web_auth_token=args.web_auth_token,
        web_device_id=args.web_device_id,
        web_user_id=args.web_user_id,
        kp_poll_seconds=args.kp_poll_seconds,
        kp_poll_interval_ms=args.kp_poll_interval_ms,
        seed_keypackage=args.seed_keypackage,
        seed_init=args.seed_group_init,
        plaintext=args.plaintext,
        send_peer_token=args.send_peer_token,
        wait_peer_app=args.wait_peer_app,
        peer_app_expected=args.peer_app_expected,
        peer_app_timeout_s=args.peer_app_timeout_s,
        peer_app_idle_timeout_s=args.peer_app_idle_timeout_s,
        gateway_ready_timeout_s=args.gateway_ready_timeout_s,
        init_command="group-init",
        command_label="gw-phase5-room-proof",
        temp_prefix="phase5-room-proof-",
    )


def _emit_phase5_coexist_report(
    *,
    label: str,
    summary: dict[str, object],
    wait_peer_app: bool,
) -> bool:
    conv_id = summary.get("conv_id", "")
    digest = summary.get("digest_sha256_b64")
    digest_status = "present" if isinstance(digest, str) and digest else "missing"
    expected_match = summary.get("peer_app_expected_match")
    if wait_peer_app and isinstance(expected_match, bool):
        status_ok = expected_match
    else:
        status_ok = not wait_peer_app or summary.get("peer_app_decrypted") is True
    status_text = "PASS" if status_ok else "FAIL"

    sys.stdout.write(f"{label}:\n")
    sys.stdout.write(f"  conv_id: {conv_id}\n")
    sys.stdout.write(f"  digest_status: {digest_status}\n")
    if digest_status == "present":
        sys.stdout.write(f"  digest_sha256_b64: {digest}\n")
    sys.stdout.write(f"  welcome_seq: {summary.get('welcome_seq')}\n")
    sys.stdout.write(f"  last_handshake_seq: {summary.get('last_handshake_seq')}\n")
    sys.stdout.write(f"  app_seq: {summary.get('app_seq')}\n")
    sys.stdout.write(f"  sent_peer_token: {summary.get('sent_peer_token')}\n")
    sys.stdout.write(f"  sent_peer_token_plaintext: {summary.get('sent_peer_token_plaintext')}\n")
    sys.stdout.write(f"  sent_peer_token_seq: {summary.get('sent_peer_token_seq')}\n")
    if "peer_app_expected" in summary:
        sys.stdout.write(f"  peer_app_expected: {summary.get('peer_app_expected')}\n")
        sys.stdout.write(f"  peer_app_expected_match: {summary.get('peer_app_expected_match')}\n")
    sys.stdout.write(f"  status: {status_text}\n")
    return status_ok


def handle_gw_phase5_coexist_proof(args: argparse.Namespace) -> int:
    repo_root = find_repo_root()
    temp_root = Path(tempfile.mkdtemp(prefix="phase5-coexist-proof-"))
    dm_state_dir = temp_root / "dm_state"
    room_state_dir = temp_root / "room_state"
    dm_transcript_path = (
        Path(args.dm_transcript_out) if args.dm_transcript_out else temp_root / "phase5_dm_transcript.json"
    )
    room_transcript_path = (
        Path(args.room_transcript_out) if args.room_transcript_out else temp_root / "phase5_room_transcript.json"
    )
    coexist_bundle_path = (
        Path(args.coexist_bundle_out) if args.coexist_bundle_out else temp_root / "phase5_coexist_bundle_v1.json"
    )

    gateway_process = None
    web_process = None
    gateway_log_file = None
    web_log_file = None
    gateway_log = None
    web_log = None
    start_time = time.time()
    try:
        services = _start_phase5_services(
            repo_root=repo_root,
            temp_root=temp_root,
            gateway_ready_timeout_s=args.gateway_ready_timeout_s,
        )
        gateway_process = services["gateway_process"]
        web_process = services["web_process"]
        gateway_log_file = services["gateway_log_file"]
        web_log_file = services["web_log_file"]
        gateway_url = services["gateway_url"]
        web_url = services["web_url"]
        gateway_log = services["gateway_log"]
        web_log = services["web_log"]

        sys.stdout.write(f"Gateway URL: {gateway_url}\n")
        sys.stdout.write(f"Web URL: {web_url}\n")
        sys.stdout.write(f"DM transcript path: {dm_transcript_path}\n")
        sys.stdout.write(f"Room transcript path: {room_transcript_path}\n")
        sys.stdout.write(f"Logs: {gateway_log} {web_log}\n")
        _emit_phase5_web_instructions(
            web_url=web_url,
            gateway_url=gateway_url,
            web_auth_token=args.web_auth_token,
            web_device_id=args.web_device_id,
        )
        if args.auto_reply_hint:
            sys.stdout.write(f"Auto-reply hint: {args.auto_reply_hint}\n")

        session = gateway_client.session_start(
            gateway_url,
            args.cli_auth_token,
            args.cli_device_id,
        )
        session_token = session["session_token"]

        sys.stdout.write("Waiting for web KeyPackage (DM)...\n")
        dm_summary = _phase5_proof_step(
            base_url=gateway_url,
            session_token=session_token,
            conv_id=args.dm_conv_id,
            group_id_b64=args.dm_group_id_b64,
            cli_state_dir=str(dm_state_dir),
            cli_user_id=args.cli_user_id,
            web_user_id=args.web_user_id,
            kp_poll_seconds=args.kp_poll_seconds,
            kp_poll_interval_ms=args.kp_poll_interval_ms,
            seed_keypackage=args.seed_keypackage,
            seed_init=args.seed_dm_init,
            plaintext=args.dm_plaintext,
            send_peer_token=args.send_peer_token,
            wait_peer_app=args.wait_peer_app,
            peer_app_expected=args.peer_app_expected,
            peer_app_timeout_s=args.peer_app_timeout_s,
            peer_app_idle_timeout_s=args.peer_app_idle_timeout_s,
            init_command="dm-init",
            command_label="gw-phase5-dm-proof",
            transcript_path=dm_transcript_path,
            print_web_cli_block=args.print_web_cli_block,
            web_cli_header="DM Web CLI block:" if args.print_web_cli_block else None,
        )

        sys.stdout.write("Waiting for web KeyPackage (Room)...\n")
        room_summary = _phase5_proof_step(
            base_url=gateway_url,
            session_token=session_token,
            conv_id=args.room_conv_id,
            group_id_b64=args.room_group_id_b64,
            cli_state_dir=str(room_state_dir),
            cli_user_id=args.cli_user_id,
            web_user_id=args.web_user_id,
            kp_poll_seconds=args.kp_poll_seconds,
            kp_poll_interval_ms=args.kp_poll_interval_ms,
            seed_keypackage=args.seed_keypackage,
            seed_init=args.seed_group_init,
            plaintext=args.room_plaintext,
            send_peer_token=args.send_peer_token,
            wait_peer_app=args.wait_peer_app,
            peer_app_expected=args.peer_app_expected,
            peer_app_timeout_s=args.peer_app_timeout_s,
            peer_app_idle_timeout_s=args.peer_app_idle_timeout_s,
            init_command="group-init",
            command_label="gw-phase5-room-proof",
            transcript_path=room_transcript_path,
            print_web_cli_block=args.print_web_cli_block,
            web_cli_header="Room Web CLI block:" if args.print_web_cli_block else None,
        )

        dm_transcript_payload = _load_json_payload(dm_transcript_path)
        room_transcript_payload = _load_json_payload(room_transcript_path)
        coexist_bundle = {
            "schema_version": "phase5_coexist_bundle_v1",
            "dm": {
                "expected_plaintext": args.dm_plaintext,
                "transcript": dm_transcript_payload,
            },
            "room": {
                "expected_plaintext": args.room_plaintext,
                "transcript": room_transcript_payload,
            },
        }
        _atomic_write_json(coexist_bundle_path, coexist_bundle)
        sys.stdout.write(f"Coexist bundle written to: {coexist_bundle_path}\n")
        sys.stdout.write("In the web UI: Phase 5 Coexist Proof → Import bundle → Run\n")

        sys.stdout.write("Phase 5 co-existence report:\n")
        dm_ok = _emit_phase5_coexist_report(
            label="DM report",
            summary=dm_summary,
            wait_peer_app=args.wait_peer_app,
        )
        room_ok = _emit_phase5_coexist_report(
            label="Room report",
            summary=room_summary,
            wait_peer_app=args.wait_peer_app,
        )
        duration_s = time.time() - start_time
        sys.stdout.write(f"Total duration_s: {duration_s:.2f}\n")
        if args.wait_peer_app:
            both_decrypted = dm_ok and room_ok
            sys.stdout.write(f"Both peer app messages decrypted: {both_decrypted}\n")
        else:
            sys.stdout.write("Both peer app messages decrypted: not requested\n")
        return 0
    finally:
        for process in [web_process, gateway_process]:
            if process and process.poll() is None:
                process.terminate()
        for process in [web_process, gateway_process]:
            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        for log_file in [web_log_file, gateway_log_file]:
            if log_file:
                log_file.close()


def handle_gw_room_init_send(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    output = _run_harness_capture(
        "group-init",
        [
            "--state-dir",
            args.state_dir,
            *_peer_keypackage_args(args.peer_kp_b64),
            "--group-id",
            args.group_id,
            "--seed",
            str(args.seed),
        ],
    )
    payload = json.loads(_first_nonempty_line(output))
    _send_welcome_commit(base_url, session_token, args.conv_id, payload)
    return 0


def handle_gw_room_add_send(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    output = _run_harness_capture(
        "group-add",
        [
            "--state-dir",
            args.state_dir,
            *_peer_keypackage_args(args.peer_kp_b64),
            "--seed",
            str(args.seed),
        ],
    )
    payload = json.loads(_first_nonempty_line(output))
    proposals = _extract_proposals(payload)
    proposal_seqs = _send_proposals(base_url, session_token, args.conv_id, proposals)
    for index, proposal_seq in enumerate(proposal_seqs, start=1):
        sys.stdout.write(f"proposal_seq_{index}: {proposal_seq}\n")
    _send_welcome_commit(base_url, session_token, args.conv_id, payload)
    return 0


def handle_gw_dm_send(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    output = _run_harness_capture(
        "dm-encrypt",
        [
            "--state-dir",
            args.state_dir,
            "--plaintext",
            args.plaintext,
        ],
    )
    ciphertext_b64 = _first_nonempty_line(output)
    env_b64 = dm_envelope.pack(0x03, ciphertext_b64)
    msg_id = _msg_id_for_env(env_b64)
    response = gateway_client.inbox_send(
        base_url,
        session_token,
        args.conv_id,
        msg_id,
        env_b64,
    )
    sys.stdout.write(f"seq: {response['seq']}\n")
    return 0


def handle_gw_phase5_room_smoke(args: argparse.Namespace) -> int:
    if args.dry_run:
        plan = _phase5_room_smoke_plan(args)
        sys.stdout.write(f"{json.dumps(plan, sort_keys=True)}\n")
        return 0

    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    identity = identity_store.load_or_create_identity(args.profile_paths.identity_path)
    add_peer_user_ids = args.add_peer_user_id or []
    transcript_events: list[dict[str, object]] = []
    welcome_env = None
    commit_env = None
    app_env = None
    app2_env = None

    _ensure_initiator_state(args.state_dir, args.seed_keypackage)

    members = [identity.user_id, *args.peer_user_id]
    try:
        gateway_client.room_create(base_url, session_token, args.conv_id, members)
    except urllib.error.HTTPError as exc:
        message = _extract_http_error_message(exc)
        if "conversation already exists" not in message:
            raise RuntimeError(f"Room creation failed: {message}") from exc
        sys.stdout.write("Room already exists; continuing.\n")

    peer_keypackages = [
        _poll_keypackage(
            base_url,
            session_token,
            peer_user_id,
            args.kp_poll_seconds,
            args.kp_poll_interval_ms,
        )
        for peer_user_id in args.peer_user_id
    ]

    output = _run_harness_capture(
        "group-init",
        [
            "--state-dir",
            args.state_dir,
            *_peer_keypackage_args(peer_keypackages),
            "--group-id",
            args.group_id_b64,
            "--seed",
            str(args.seed_group_init),
        ],
    )
    payload = json.loads(_first_nonempty_line(output))
    welcome_env = dm_envelope.pack(0x01, str(payload["welcome"]))
    commit_env = dm_envelope.pack(0x02, str(payload["commit"]))

    welcome_seq = _send_envelope(base_url, session_token, args.conv_id, welcome_env)
    _append_transcript_event(transcript_events, welcome_seq, welcome_env)
    commit_seq = _send_envelope(base_url, session_token, args.conv_id, commit_env)
    _append_transcript_event(transcript_events, commit_seq, commit_env)

    app_output = _run_harness_capture(
        "dm-encrypt",
        [
            "--state-dir",
            args.state_dir,
            "--plaintext",
            "phase5-room-smoke",
        ],
    )
    app_ciphertext = _first_nonempty_line(app_output)
    app_env = dm_envelope.pack(0x03, app_ciphertext)
    app_seq = _send_envelope(base_url, session_token, args.conv_id, app_env)
    _append_transcript_event(transcript_events, app_seq, app_env)

    summary = {
        "app_seq": app_seq,
        "command": "gw-phase5-room-smoke",
        "commit_seq": commit_seq,
        "conv_id": args.conv_id,
        "welcome_seq": welcome_seq,
    }
    if add_peer_user_ids:
        add_peer_keypackages = [
            _poll_keypackage(
                base_url,
                session_token,
                peer_user_id,
                args.kp_poll_seconds,
                args.kp_poll_interval_ms,
            )
            for peer_user_id in add_peer_user_ids
        ]
        add_output = _run_harness_capture(
            "group-add",
            [
                "--state-dir",
                args.state_dir,
                *_peer_keypackage_args(add_peer_keypackages),
                "--seed",
                str(args.seed_group_add),
            ],
        )
        add_payload = json.loads(_first_nonempty_line(add_output))
        add_proposals = _extract_proposals(add_payload)
        add_proposal_seqs = _send_proposals_with_events(
            base_url,
            session_token,
            args.conv_id,
            add_proposals,
            transcript_events,
        )
        add_welcome_env = dm_envelope.pack(0x01, str(add_payload["welcome"]))
        add_commit_env = dm_envelope.pack(0x02, str(add_payload["commit"]))
        add_welcome_seq = _send_envelope(base_url, session_token, args.conv_id, add_welcome_env)
        _append_transcript_event(transcript_events, add_welcome_seq, add_welcome_env)
        add_commit_seq = _send_envelope(base_url, session_token, args.conv_id, add_commit_env)
        _append_transcript_event(transcript_events, add_commit_seq, add_commit_env)

        app2_output = _run_harness_capture(
            "dm-encrypt",
            [
                "--state-dir",
                args.state_dir,
                "--plaintext",
                args.plaintext2,
            ],
        )
        app2_ciphertext = _first_nonempty_line(app2_output)
        app2_env = dm_envelope.pack(0x03, app2_ciphertext)
        app2_seq = _send_envelope(base_url, session_token, args.conv_id, app2_env)
        _append_transcript_event(transcript_events, app2_seq, app2_env)
        summary.update(
            {
                "add_commit_seq": add_commit_seq,
                "add_proposal_seqs": add_proposal_seqs,
                "add_welcome_seq": add_welcome_seq,
                "app2_seq": app2_seq,
            }
        )
    if args.transcript_out:
        transcript_path = Path(args.transcript_out)
        transcript_payload = _build_transcript_payload(args.conv_id, transcript_events)
        _atomic_write_json(transcript_path, transcript_payload)
    if args.print_web_cli_block:
        expected_plaintext = args.plaintext2 if app2_env else "phase5-room-smoke"
        _emit_web_cli_block(
            conv_id=args.conv_id,
            welcome_env=welcome_env,
            commit_env=commit_env,
            app_env=app_env,
            expected_plaintext=expected_plaintext,
        )
    sys.stdout.write(f"{json.dumps(summary, sort_keys=True)}\n")
    return 0


def handle_gw_dm_tail(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    joined = _state_dir_has_data(Path(args.state_dir))
    pending_path = _pending_commits_path(args.state_dir)
    pending_commits = _load_pending_commits(pending_path)
    if args.wipe_state:
        if args.from_seq is None:
            raise RuntimeError("--wipe-state requires --from-seq (use --from-seq 1 to rebuild state)")
        state_path = Path(args.state_dir)
        if state_path.exists() and not state_path.is_dir():
            raise RuntimeError(f"Refusing to wipe non-directory state_dir: {state_path}")
        if state_path.is_dir():
            shutil.rmtree(state_path)
        if pending_path.exists():
            pending_path.unlink()
        pending_commits = {}
        from_seq = args.from_seq
    else:
        from_seq = (
            args.from_seq
            if args.from_seq is not None
            else gateway_store.get_next_seq(args.conv_id, args.profile_paths.cursors_path)
        )
    if joined and pending_commits:
        _flush_pending_commits(args.state_dir, pending_commits, pending_path)
    for event in gateway_client.sse_tail(
        base_url,
        session_token,
        args.conv_id,
        from_seq,
        max_events=args.max_events,
        idle_timeout_s=args.idle_timeout_s,
    ):
        body = event.get("body", {})
        seq = body.get("seq")
        env_b64 = body.get("env")
        if not isinstance(seq, int) or not isinstance(env_b64, str):
            continue
        kind, payload_b64 = dm_envelope.unpack(env_b64)
        if kind == 0x01:
            _run_harness_capture(
                "dm-join",
                [
                    "--state-dir",
                    args.state_dir,
                    "--welcome",
                    payload_b64,
                ],
            )
            joined = True
            if pending_commits:
                _flush_pending_commits(args.state_dir, pending_commits, pending_path)
        elif kind == 0x02:
            if not joined:
                _buffer_pending_commit(pending_path, pending_commits, seq, payload_b64)
            else:
                returncode, stdout, stderr = _run_harness_capture_with_status(
                    "dm-commit-apply",
                    [
                        "--state-dir",
                        args.state_dir,
                        "--commit",
                        payload_b64,
                    ],
                )
                if returncode != 0:
                    message = stderr.strip() or stdout.strip()
                    if _is_uninitialized_commit_error(message):
                        joined = False
                        _buffer_pending_commit(pending_path, pending_commits, seq, payload_b64)
                    else:
                        sys.stderr.write(stderr)
                        raise RuntimeError("harness dm-commit-apply failed")
                else:
                    joined = True
        elif kind == 0x03:
            output = _run_harness_capture(
                "dm-decrypt",
                [
                    "--state-dir",
                    args.state_dir,
                    "--ciphertext",
                    payload_b64,
                ],
            )
            plaintext = _first_nonempty_line(output)
            sys.stdout.write(f"{plaintext}\n")
        if args.ack:
            gateway_client.inbox_ack(base_url, session_token, args.conv_id, seq)
            gateway_store.update_next_seq(args.conv_id, seq, args.profile_paths.cursors_path)
    return 0


def handle_dm_keypackage(args: argparse.Namespace) -> int:
    return run_harness(
        "dm-keypackage",
        [
            "--state-dir",
            args.state_dir,
            "--name",
            args.name,
            "--seed",
            str(args.seed),
        ],
    )


def handle_dm_init(args: argparse.Namespace) -> int:
    return run_harness(
        "dm-init",
        [
            "--state-dir",
            args.state_dir,
            "--peer-keypackage",
            args.peer_keypackage,
            "--group-id",
            args.group_id,
            "--seed",
            str(args.seed),
        ],
    )


def handle_dm_join(args: argparse.Namespace) -> int:
    return run_harness(
        "dm-join",
        [
            "--state-dir",
            args.state_dir,
            "--welcome",
            args.welcome,
        ],
    )


def handle_dm_commit_apply(args: argparse.Namespace) -> int:
    return run_harness(
        "dm-commit-apply",
        [
            "--state-dir",
            args.state_dir,
            "--commit",
            args.commit,
        ],
    )


def handle_dm_encrypt(args: argparse.Namespace) -> int:
    return run_harness(
        "dm-encrypt",
        [
            "--state-dir",
            args.state_dir,
            "--plaintext",
            args.plaintext,
        ],
    )


def handle_dm_decrypt(args: argparse.Namespace) -> int:
    return run_harness(
        "dm-decrypt",
        [
            "--state-dir",
            args.state_dir,
            "--ciphertext",
            args.ciphertext,
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.profile_paths = profile_paths.resolve_profile_paths(args.profile)

    try:
        if args.command == "vectors":
            return handle_vectors(args)
        if args.command == "smoke":
            return handle_smoke(args)
        if args.command == "soak":
            return handle_soak(args)
        if args.command == "whoami":
            return handle_whoami(args)
        if args.command == "dm-keypackage":
            return handle_dm_keypackage(args)
        if args.command == "dm-init":
            return handle_dm_init(args)
        if args.command == "dm-join":
            return handle_dm_join(args)
        if args.command == "dm-commit-apply":
            return handle_dm_commit_apply(args)
        if args.command == "dm-encrypt":
            return handle_dm_encrypt(args)
        if args.command == "dm-decrypt":
            return handle_dm_decrypt(args)
        if args.command == "gw-start":
            return handle_gw_start(args)
        if args.command == "gw-resume":
            return handle_gw_resume(args)
        if args.command == "gw-send":
            return handle_gw_send(args)
        if args.command == "gw-ack":
            return handle_gw_ack(args)
        if args.command == "gw-tail":
            return handle_gw_tail(args)
        if args.command == "gw-kp-publish":
            return handle_gw_kp_publish(args)
        if args.command == "gw-kp-fetch":
            return handle_gw_kp_fetch(args)
        if args.command == "gw-dm-create":
            return handle_gw_dm_create(args)
        if args.command == "gw-room-create":
            return handle_gw_room_create(args)
        if args.command == "gw-room-invite":
            return handle_gw_room_invite(args)
        if args.command == "gw-room-remove":
            return handle_gw_room_remove(args)
        if args.command == "gw-room-promote":
            return handle_gw_room_promote(args)
        if args.command == "gw-room-demote":
            return handle_gw_room_demote(args)
        if args.command == "gw-dm-init-send":
            return handle_gw_dm_init_send(args)
        if args.command == "gw-room-init-send":
            return handle_gw_room_init_send(args)
        if args.command == "gw-room-add-send":
            return handle_gw_room_add_send(args)
        if args.command == "gw-dm-send":
            return handle_gw_dm_send(args)
        if args.command == "gw-phase5-room-smoke":
            return handle_gw_phase5_room_smoke(args)
        if args.command == "gw-phase5-dm-proof":
            return handle_gw_phase5_dm_proof(args)
        if args.command == "gw-phase5-room-proof":
            return handle_gw_phase5_room_proof(args)
        if args.command == "gw-phase5-coexist-proof":
            return handle_gw_phase5_coexist_proof(args)
        if args.command == "gw-dm-tail":
            return handle_gw_dm_tail(args)
    except RuntimeError as exc:  # user-facing errors
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
