"""CLI POC for running MLS harness scenarios locally."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
from pathlib import Path
from typing import Iterable, Tuple

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
    welcome_env: str | None,
    commit_env: str | None,
    app_env: str | None,
    expected_plaintext: str,
) -> None:
    lines: list[str] = []
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
        if args.command == "gw-dm-tail":
            return handle_gw_dm_tail(args)
    except RuntimeError as exc:  # user-facing errors
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
