"""Client CLI placeholder."""

from __future__ import annotations

import argparse
from typing import TextIO


def build_message(target: str) -> str:
    """Return a simple greeting for the provided target."""

    clean_target = target.strip() or "world"
    return f"hello from cli, {clean_target}"


def main(argv: list[str] | None = None, output: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description="Client CLI placeholder")
    parser.add_argument("target", nargs="?", default="world", help="recipient name")
    args = parser.parse_args(argv)

    message = build_message(args.target)
    stream = output or print

    if callable(stream):
        stream(message)
    else:
        stream.write(message + "\n")

    return 0


if __name__ == "__main__":  # pragma: no cover - convenience execution
    raise SystemExit(main())
