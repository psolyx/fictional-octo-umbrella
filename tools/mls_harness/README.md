# MLS correctness harness (Phase 0)

This tool runs deterministic MLS scenarios to exercise two-party direct messages using the Go MLS library (`github.com/cisco/go-mls`, pinned and vendored).

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

## Deterministic vector verification (CI anchor)
`vectors` mode runs a fixed two-party scenario, captures a transcript digest, and checks it against the committed vector file under `tools/mls_harness/vectors/`.

From the harness directory:

```sh
env GOFLAGS=-mod=vendor GOTOOLCHAIN=local go run ./cmd/mls-harness vectors --vector-file ./vectors/dm_smoke_v1.json
```

This provides a small conformance anchor for CI without requiring a long soak.

## Soak test (Phase 0 proof)
The `soak` subcommand mirrors `smoke` but runs a longer proof test with periodic persistence:

```sh
go -C tools/mls_harness run ./cmd/mls-harness soak --iterations 1000 --save-every 50 --state-dir /tmp/mls-soak
```

This is intended for manual execution to validate the Phase 0 1k-message requirement.

## Persistence format
State is serialized via Go's `gob` encoder into per-participant files (alice.gob, bob.gob) under the provided state directory. These files contain MLS secrets solely for test purposes; keep them local and out of version control.

## Python smoke test integration
`gateway/tests/test_mls_harness_smoke.py` runs the smoke scenario with small parameters. The test:
- Skips automatically if the Go toolchain is unavailable.
- Invokes `go -C tools/mls_harness run ./cmd/mls-harness smoke --iterations 50 --save-every 10` using a temporary state directory with vendored dependencies.

`gateway/tests/test_mls_harness_vectors.py` runs the deterministic vector verification during CI.

## No Rust policy
This harness is intentionally Go-first. Do not introduce Rust code or Rust->WASM toolchains; browsers will rely on a TypeScript MLS path or a constrained Go->WASM fallback per ADR 0004.
