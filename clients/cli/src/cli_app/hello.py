"""Client CLI with social integration."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TextIO

from . import identity_store, social


def build_message(target: str) -> str:
    """Return a simple greeting for the provided target."""

    clean_target = target.strip() or "world"
    return f"hello from cli, {clean_target}"


def _emit(output: TextIO | None, message: str) -> None:
    stream = output or print
    if callable(stream):
        stream(message)
    else:
        stream.write(str(message) + "\n")


def _normalize_social_args(args_list: list[str]) -> list[str]:
    normalized: list[str] = []
    idx = 0
    while idx < len(args_list):
        arg = args_list[idx]
        if arg == "--user_id" and idx + 1 < len(args_list):
            normalized.append(f"--user_id={args_list[idx + 1]}")
            idx += 2
            continue
        normalized.append(arg)
        idx += 1
    return normalized


def main(argv: list[str] | None = None, output: TextIO | None = None) -> int:
    args_list = argv if argv is not None else sys.argv[1:]
    if not args_list or args_list[0] != "social":
        target = args_list[0] if args_list else "world"
        _emit(output, build_message(target))
        return 0

    base_url_default = os.environ.get("GATEWAY_URL", "http://localhost:8080")
    parser = argparse.ArgumentParser(description="Polycentric CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish_parser = subparsers.add_parser("publish", help="publish a social event")
    publish_parser.add_argument("--kind", required=True, help="event kind, e.g. post")
    publish_parser.add_argument("--payload", required=True, help="JSON payload string")
    publish_parser.add_argument("--prev-hash", dest="prev_hash", default=None, help="previous head hash if known")
    publish_parser.add_argument("--gateway-url", default=base_url_default, help="gateway base URL")
    publish_parser.add_argument(
        "--identity-path",
        default=identity_store.DEFAULT_IDENTITY_PATH,
        help="path to persisted identity",
    )

    fetch_parser = subparsers.add_parser("fetch", help="fetch social events")
    fetch_parser.add_argument(
        "--user_id",
        required=False,
        default=None,
        help="user_id to fetch; defaults to the local identity",
    )
    fetch_parser.add_argument("--limit", type=int, default=20, help="max events to return")
    fetch_parser.add_argument("--after-hash", dest="after_hash", default=None, help="optional cursor hash")
    fetch_parser.add_argument("--gateway-url", default=base_url_default, help="gateway base URL")
    fetch_parser.add_argument(
        "--identity-path",
        default=identity_store.DEFAULT_IDENTITY_PATH,
        help="path to persisted identity",
    )

    args = parser.parse_args(_normalize_social_args(args_list[1:]))

    try:
        if args.command == "publish":
            identity = identity_store.load_or_create_identity(args.identity_path)
            payload = json.loads(args.payload)
            event = social.publish_social_event(
                args.gateway_url,
                identity=identity,
                kind=args.kind,
                payload=payload,
                prev_hash=args.prev_hash,
            )
            _emit(output, json.dumps(event, sort_keys=True))
            return 0
        if args.command == "fetch":
            identity = identity_store.load_or_create_identity(args.identity_path)
            user_id = args.user_id or identity.user_id
            events = social.fetch_social_events(
                args.gateway_url,
                user_id=user_id,
                limit=args.limit,
                after_hash=args.after_hash,
            )
            _emit(output, json.dumps(events, sort_keys=True))
            return 0
    except Exception as exc:  # pragma: no cover - exercised in tests
        _emit(output, f"error: {exc}")
        return 1

    return 1


if __name__ == "__main__":  # pragma: no cover - convenience execution
    raise SystemExit(main())
