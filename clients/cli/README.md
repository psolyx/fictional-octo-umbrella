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
```

- `vectors` uses the default vector file at `tools/mls_harness/vectors/dm_smoke_v1.json` unless overridden.
- `smoke` defaults to 50 iterations and saves every 10 messages.
- `soak` defaults to 1000 iterations and saves every 50 messages (manual proof run).

## Persistence warning
`--state-dir` will contain serialized MLS state and secrets. Keep it local and **never** commit it to version control.
