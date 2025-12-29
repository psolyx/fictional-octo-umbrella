"""Gateway core shim with a lightweight simulation CLI."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Callable, Iterable, TextIO

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is not None:  # pragma: no cover - exercised when deps installed
    from aiohttp import web
else:  # pragma: no cover - offline fallback
    from gateway.aiohttp_stub import web

from .cursors import CursorStore
from .hub import SubscriptionHub
from .log import ConversationEvent, ConversationLog
from .ws_transport import create_app


def greet(name: str = "world") -> str:
    """Return a friendly greeting for the provided name."""

    clean_name = name.strip() or "world"
    return f"Hello, {clean_name}!"


def simulate(frames: Iterable[dict], output: TextIO) -> None:
    """Process JSON frames through the gateway core and emit events."""

    log = ConversationLog()
    hub = SubscriptionHub()
    cursors = CursorStore()
    callbacks: dict[str, Callable[[ConversationEvent], None]] = {}

    def callback_for(device_id: str):
        if device_id not in callbacks:
            def _callback(event: ConversationEvent, device: str = device_id) -> None:
                message = {
                    "t": "event",
                    "device_id": device,
                    "conv_id": event.conv_id,
                    "seq": event.seq,
                    "msg_id": event.msg_id,
                    "envelope_b64": event.envelope_b64,
                    "sender_device_id": event.sender_device_id,
                    "ts_ms": event.ts_ms,
                }
                output.write(json.dumps(message) + "\n")

            callbacks[device_id] = _callback
        return callbacks[device_id]

    for frame in frames:
        frame_type = frame.get("t")
        if frame_type == "conv.subscribe":
            device_id = frame["device_id"]
            conv_id = frame["conv_id"]
            hub.subscribe(device_id, conv_id, callback_for(device_id))
        elif frame_type == "conv.send":
            conv_id = frame["conv_id"]
            msg_id = frame["msg_id"]
            envelope_b64 = frame["envelope_b64"]
            sender_device_id = frame["sender_device_id"]
            ts_ms = frame["ts_ms"]
            _, event, created = log.append(conv_id, msg_id, envelope_b64, sender_device_id, ts_ms)
            if created:
                hub.broadcast(event)
        elif frame_type == "conv.ack":
            cursors.ack(frame["device_id"], frame["conv_id"], frame["seq"])
        elif frame_type == "conv.replay":
            conv_id = frame["conv_id"]
            device_id = frame["device_id"]
            from_seq = frame.get("from_seq")
            after_seq = frame.get("after_seq")
            limit = frame.get("limit")
            if from_seq is None:
                if after_seq is not None:
                    from_seq = after_seq + 1
                else:
                    from_seq = cursors.next_seq(device_id, conv_id)
            events = log.list_from(conv_id, from_seq, limit)
            for event in events:
                hub.broadcast(event)
        else:
            raise ValueError(f"unsupported frame type: {frame_type}")


def _load_frames(handle: TextIO) -> Iterable[dict]:
    content = handle.read()
    if not content.strip():
        return []

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        frames: list[dict] = []
        for line in content.splitlines():
            if line.strip():
                frames.append(json.loads(line))
        return frames

    if isinstance(parsed, list):
        return parsed
    return [parsed]


def _run_simulation(args: argparse.Namespace, output: TextIO) -> int:
    frames = _load_frames(args.file or sys.stdin)
    simulate(frames, output)
    return 0


def _run_greet(name: str, output: TextIO | None) -> int:
    message = greet(name)
    stream = output or print

    if callable(stream):
        stream(message)
    else:
        stream.write(message + "\n")
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    app = create_app(ping_interval_s=args.ping_interval, db_path=args.db)
    web.run_app(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None, output: TextIO | None = None) -> int:
    """Entry point for CLI commands."""

    if argv is None:
        argv = sys.argv[1:]

    if not argv or (argv[0] not in {"simulate", "greet", "serve"} and not argv[0].startswith("-")):
        name = argv[0] if argv else "world"
        return _run_greet(name, output)

    parser = argparse.ArgumentParser(description="Gateway CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    greet_parser = subparsers.add_parser("greet", help="Emit a greeting")
    greet_parser.add_argument("name", nargs="?", default="world", help="Who to greet")

    simulate_parser = subparsers.add_parser("simulate", help="Simulate gateway core frames")
    simulate_parser.add_argument(
        "-f",
        "--file",
        type=argparse.FileType("r"),
        default=None,
        help="Path to JSON frames file; defaults to stdin",
    )

    serve_parser = subparsers.add_parser("serve", help="Run the aiohttp gateway server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    serve_parser.add_argument("--port", type=int, default=8080, help="Port to bind")
    serve_parser.add_argument(
        "--ping-interval",
        type=int,
        default=30,
        help="Seconds between heartbeat pings",
    )
    serve_parser.add_argument("--db", type=str, default=None, help="Path to SQLite database for durability")

    args = parser.parse_args(argv)

    if args.command == "simulate":
        return _run_simulation(args, output or sys.stdout)
    if args.command == "serve":
        return _run_serve(args)

    return _run_greet(args.name, output)


if __name__ == "__main__":  # pragma: no cover - convenience execution
    raise SystemExit(main())
