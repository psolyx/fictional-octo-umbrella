# MLS correctness harness (Phase 0)

This tool runs a deterministic MLS smoke scenario to exercise two-party direct messages using the Go MLS library (`github.com/cisco/go-mls`, pinned and vendored).

## What it does
- Creates two deterministic participants (alice, bob) using the MLS X25519_AES128GCM_SHA256_Ed25519 ciphersuite.
- Forms a two-member group, exchanges encrypted application messages in a loop, and periodically persists and reloads MLS state.
- Stays offline-friendly: all dependencies are vendored and no network calls are made at runtime.

## Running the smoke scenario
From the repo root:

```sh
go -C tools/mls_harness run ./cmd/mls-harness smoke --iterations 50 --save-every 10 --state-dir /tmp/mls-state
```

- `--state-dir` must point to a writable directory; it will contain serialized MLS state (secrets included) and **must not** be committed.
- Adjust `--iterations` and `--save-every` to change message volume and persistence checkpoints.

## Persistence format
State is serialized via Go's `gob` encoder into per-participant files (alice.gob, bob.gob) under the provided state directory. These files contain MLS secrets solely for test purposes; keep them local and out of version control.

## Python smoke test integration
`gateway/tests/test_mls_harness_smoke.py` runs the smoke scenario with small parameters. The test:
- Skips automatically if the Go toolchain is unavailable.
- Invokes `go -C tools/mls_harness run ./cmd/mls-harness smoke --iterations 50 --save-every 10` using a temporary state directory with vendored dependencies.

## No Rust policy
This harness is intentionally Go-first. Do not introduce Rust code or Rust->WASM toolchains; browsers will rely on a TypeScript MLS path or a constrained Go->WASM fallback per ADR 0004.
