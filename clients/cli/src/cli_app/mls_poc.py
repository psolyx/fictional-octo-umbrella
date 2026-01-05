import argparse
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from cli_app import identity_store, polycentric_ed25519

MIN_GO_VERSION = polycentric_ed25519.MIN_GO_VERSION


def find_repo_root() -> Path:
    """Find the repository root by walking parents from this file."""

    return polycentric_ed25519.find_repo_root()


def parse_go_version(raw: str) -> Tuple[int, int, int]:
    return polycentric_ed25519.parse_go_version(raw)


def detect_go_version(go_path: str) -> Tuple[int, int, int]:
    return polycentric_ed25519.detect_go_version(go_path)


def ensure_go_ready() -> str:
    return polycentric_ed25519.ensure_go_ready()


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


# Remaining functions unchanged

def build_parser() -> argparse.ArgumentParser:
    repo_root = find_repo_root()
    default_vector = repo_root / "tools" / "mls_harness" / "vectors" / "dm_smoke_v1.json"

    parser = argparse.ArgumentParser(description="MLS DM POC using the Go harness")
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
        default=str(identity_store.DEFAULT_IDENTITY_PATH),
        help="Path to identity JSON (default: ~/.polycentric_demo/identity.json)",
    )

    social = subparsers.add_parser("social", help="Publish or view social events")
    social_sub = social.add_subparsers(dest="social_command", required=True)

    publish = social_sub.add_parser("publish", help="Publish a short text event")
    publish.add_argument("--text", required=True, help="Text body to publish")
    publish.add_argument("--gateway", default="http://127.0.0.1:8080", help="Gateway base URL")
    publish.add_argument(
        "--identity-file",
        default=str(identity_store.DEFAULT_IDENTITY_PATH),
        help="Path to identity JSON (default: ~/.polycentric_demo/identity.json)",
    )

    feed = social_sub.add_parser("feed", help="Fetch a user feed")
    feed.add_argument("--user-id", help="User id to fetch (default: self)")
    feed.add_argument("--gateway", default="http://127.0.0.1:8080", help="Gateway base URL")
    feed.add_argument("--limit", type=int, default=5, help="Maximum events to fetch")
    feed.add_argument(
        "--identity-file",
        default=str(identity_store.DEFAULT_IDENTITY_PATH),
        help="Path to identity JSON (default: ~/.polycentric_demo/identity.json)",
    )

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
    path = Path(args.identity_file)
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


def _handle_social_publish(args: argparse.Namespace) -> int:
    from cli_app import social_client

    identity = identity_store.load_or_create_identity(args.identity_file)
    event = social_client.publish_text(args.gateway, identity, args.text)
    sys.stdout.write(json.dumps(event, indent=2) + "\n")
    return 0


def _handle_social_feed(args: argparse.Namespace) -> int:
    from cli_app import social_client

    identity = identity_store.load_or_create_identity(args.identity_file)
    user_id = args.user_id or identity.user_id
    feed = social_client.fetch_feed(args.gateway, user_id, limit=args.limit)
    sys.stdout.write(json.dumps(feed, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "vectors":
            return handle_vectors(args)
        if args.command == "smoke":
            return handle_smoke(args)
        if args.command == "soak":
            return handle_soak(args)
        if args.command == "whoami":
            return handle_whoami(args)
        if args.command == "social":
            if args.social_command == "publish":
                return _handle_social_publish(args)
            if args.social_command == "feed":
                return _handle_social_feed(args)
    except RuntimeError as exc:  # user-facing errors
        sys.stderr.write(f"error: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - convenience
    raise SystemExit(main())
