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
from pathlib import Path
from typing import Iterable, Tuple

from cli_app import dm_envelope, gateway_client, gateway_store, identity_store, profile_paths

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


def run_harness(subcommand: str, extra_args: Iterable[str]) -> int:
    repo_root = find_repo_root()
    go_path = ensure_go_ready()

    harness_dir = repo_root / "tools" / "mls_harness"
    cmd = [
        go_path,
        "run",
        "-p",
        "1",
        "./cmd/mls-harness",
        subcommand,
        *extra_args,
    ]

    env = os.environ.copy()
    env.update(
        {
            "GOTOOLCHAIN": "local",
            "GOFLAGS": "-mod=vendor",
            "GOMAXPROCS": "1",
            "GOMEMLIMIT": "700MiB",
        }
    )

    result = subprocess.run(
        cmd,
        cwd=str(harness_dir),
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def _run_harness_capture(subcommand: str, extra_args: Iterable[str]) -> str:
    repo_root = find_repo_root()
    go_path = ensure_go_ready()

    harness_dir = repo_root / "tools" / "mls_harness"
    cmd = [
        go_path,
        "run",
        "-p",
        "1",
        "./cmd/mls-harness",
        subcommand,
        *extra_args,
    ]

    env = os.environ.copy()
    env.update(
        {
            "GOTOOLCHAIN": "local",
            "GOFLAGS": "-mod=vendor",
            "GOMAXPROCS": "1",
            "GOMEMLIMIT": "700MiB",
        }
    )

    result = subprocess.run(
        cmd,
        cwd=str(harness_dir),
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"harness {subcommand} failed")
    return result.stdout


def _first_nonempty_line(output: str) -> str:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    raise RuntimeError("harness output was empty")


def _msg_id_for_env(env_b64: str) -> str:
    env_bytes = base64.b64decode(env_b64)
    return hashlib.sha256(env_bytes).hexdigest()


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

    gw_dm_init = subparsers.add_parser("gw-dm-init-send", help="Init a DM and send Welcome/Commit via gateway")
    gw_dm_init.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_dm_init.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_dm_init.add_argument("--peer-kp-b64", required=True, help="Peer KeyPackage (base64, required)")
    gw_dm_init.add_argument("--group-id", required=True, help="Group id (base64, required)")
    gw_dm_init.add_argument("--seed", type=int, default=7331, help="Deterministic seed (default: 7331)")
    gw_dm_init.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

    gw_dm_send = subparsers.add_parser("gw-dm-send", help="Encrypt and send a DM application message")
    gw_dm_send.add_argument("--conv-id", required=True, help="Conversation id (required)")
    gw_dm_send.add_argument("--state-dir", required=True, help="Directory to store MLS state (required)")
    gw_dm_send.add_argument("--plaintext", required=True, help="Plaintext message (required)")
    gw_dm_send.add_argument("--base-url", help="Gateway base URL (defaults to stored session)")

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


def handle_gw_dm_tail(args: argparse.Namespace) -> int:
    base_url, session_token = _load_session(args.base_url, args.profile_paths.session_path)
    if args.wipe_state:
        if args.from_seq is None:
            raise RuntimeError("--wipe-state requires --from-seq (use --from-seq 1 to rebuild state)")
        state_path = Path(args.state_dir)
        if state_path.exists() and not state_path.is_dir():
            raise RuntimeError(f"Refusing to wipe non-directory state_dir: {state_path}")
        if state_path.is_dir():
            shutil.rmtree(state_path)
        from_seq = args.from_seq
    else:
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
        elif kind == 0x02:
            _run_harness_capture(
                "dm-commit-apply",
                [
                    "--state-dir",
                    args.state_dir,
                    "--commit",
                    payload_b64,
                ],
            )
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
        if args.command == "gw-dm-init-send":
            return handle_gw_dm_init_send(args)
        if args.command == "gw-dm-send":
            return handle_gw_dm_send(args)
        if args.command == "gw-dm-tail":
            return handle_gw_dm_tail(args)
    except RuntimeError as exc:  # user-facing errors
        sys.stderr.write(f"Error: {exc}\n")
        return 1

    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
