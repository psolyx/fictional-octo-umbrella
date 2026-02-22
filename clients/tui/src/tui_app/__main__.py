"""Thin runnable wrapper for the production TUI deliverable."""

from cli_app.tui_app import main as cli_tui_main


def main() -> int:
    return cli_tui_main()


if __name__ == "__main__":
    raise SystemExit(main())
