# MLS library selection (Go-first)

## Status
Proposed

## Context
- Roadmap Phase 0 requires an MLS correctness harness and library selection to retire early protocol risks.
- Repository hard constraint: No Rust anywhere; Go is the native implementation language for MLS components.
- CI and development environments have limited network access; offline-friendly builds and vendoring are required.
- We need a path for both native (CLI/TUI/service) environments and browsers, with deterministic harness behavior for testing.
- The MLS ecosystem is still maturing; available Go libraries have limited stability and documentation.

## Decision
- Native implementation language: Go. No Rust bindings or toolchains will be introduced.
- Library selection (native harness/POC): use `github.com/cisco/go-mls` pinned to commit/tag `v0.0.0-20210331162924-158a3829b839`.
  - Rationale: longstanding open-source implementation, permissive license, straightforward API matching current harness needs (state creation, add/commit, protect/unprotect), and minimal transitive dependencies compatible with vendoring.
  - Limitations: pre-1.0 API with sparse documentation and limited maintenance signals; treat as POC-grade with extra harness validation.
- Browser strategy (no Rust→WASM):
  - Primary plan: evaluate pure TypeScript MLS implementations for direct browser use to avoid Rust/WASM entirely.
  - Fallback plan: explore Go→WASM (GOOS=js/wasm or TinyGo) builds of the Go harness/library, with explicit risks around bundle size, performance, and API surface stability. Only adopt if TypeScript coverage proves insufficient.
- Correctness harness definition:
  - Deterministic scenario runner (fixed seeds) covering two-party DM flows first.
  - Persistence and reload checkpoints to validate state durability across iterations.
  - Replay/out-of-order robustness focused on client state handling (not Delivery Service ordering).
- Build constraints: vendor Go dependencies; avoid network calls at runtime/tests; skip cleanly if Go toolchain is unavailable.

## Consequences
- The Go MLS harness is the first-class POC path; Rust implementations remain out of scope.
- Vendored Go dependencies support offline CI; upgrades require explicit version bumps and re-vendoring.
- Browser MLS will proceed via TypeScript-first evaluation, with Go→WASM only as a constrained fallback.
- Harness work must emphasize determinism, persistence round-trips, and message replay handling to mitigate MLS maturity risks before broader rollout.
