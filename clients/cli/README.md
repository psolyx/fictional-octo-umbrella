# CLI MLS POC

This is a local proof-of-concept wrapper around the Go-based MLS harness that demonstrates two-party direct message basics. It is not a production chat client yet.

## What it does
- Invokes the vendored Go harness under `tools/mls_harness` to drive MLS scenarios.
- Provides quick vector verification (deterministic) and short/long persistence runs.
- Persists MLS state locally so you can reload and continue after checkpoints.

## Requirements
- Go toolchain **>= 1.22** available on `PATH`.
- No network fetches: harness uses vendored dependencies with `GOFLAGS=-mod=vendor` and `GOTOOLCHAIN=local`.
- **No Rust:** do not add Rust dependencies or artifacts.

## Commands
All commands are run from the repo root via the Python module entrypoint:

```sh
python -m cli_app.mls_poc vectors
python -m cli_app.mls_poc smoke --state-dir /tmp/mls-cli-poc --iterations 50 --save-every 10
python -m cli_app.mls_poc soak  --state-dir /tmp/mls-cli-poc --iterations 1000 --save-every 50
PYTHONPATH=clients/cli/src python -m cli_app.tui_app  # curses TUI shell
```

- `vectors` uses the default vector file at `tools/mls_harness/vectors/dm_smoke_v1.json` unless overridden.
- `smoke` defaults to 50 iterations and saves every 10 messages.
- `soak` defaults to 1000 iterations and saves every 50 messages (manual proof run).
- The TUI provides keyboard-only navigation (Tab/Shift-Tab to change panes, arrows to move, Enter to run) and persists the
  last used parameters to `~/.mls_tui_state.json` for offline reuse.

### Identity and device provisioning
- The CLI and TUI create an offline Polycentric scaffold at `~/.polycentric_demo/identity.json` consisting of:
  - `auth_token` representing the Polycentric system public key (user identity).
  - `user_id` derived from the auth token (used by gateway session flows).
  - `device_id` and `device_credential` placeholders compatible with gateway `session.start` expectations.
- `python -m cli_app.mls_poc whoami` prints the current user/device identifiers; the TUI header shows the same info.
- The TUI menu includes `rotate_device` to rotate only the device fields without changing the user identity.

## Persistence warning
`--state-dir` will contain serialized MLS state and secrets. Keep it local and **never** commit it to version control.
The TUI exposes the same flag: choose a private `state_dir` path before running smoke/soak.
`~/.polycentric_demo/identity.json` and any TUI state files also contain secrets; do not commit or share them.
