# TUI client entrypoint (Phase 5.2)

This package is now a thin runnable wrapper around the curses client in `clients/cli/src/cli_app/tui_app.py`.

## Run
```bash
PYTHONPATH=clients/tui/src:clients/cli/src python -m tui_app
```

`PYTHONPATH` currently needs both trees so the wrapper can import `cli_app.tui_app`.
