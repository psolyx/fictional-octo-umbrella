"""Minimal gateway placeholder.

Provides a simple greeting handler to stand in for the real gateway
behavior until the full implementation is available.
"""

from __future__ import annotations

import argparse
from typing import TextIO


def greet(name: str = "world") -> str:
    """Return a friendly greeting for the provided name."""

    clean_name = name.strip() or "world"
    return f"Hello, {clean_name}!"


def main(argv: list[str] | None = None, output: TextIO | None = None) -> int:
    """Entry point for a lightweight CLI shim.

    This keeps the component runnable while the real gateway is built out.
    """

    parser = argparse.ArgumentParser(description="Gateway placeholder CLI")
    parser.add_argument("name", nargs="?", default="world", help="Who to greet")
    args = parser.parse_args(argv)

    message = greet(args.name)
    stream = output or print

    if callable(stream):
        stream(message)
    else:
        stream.write(message + "\n")

    return 0


if __name__ == "__main__":  # pragma: no cover - convenience execution
    raise SystemExit(main())
