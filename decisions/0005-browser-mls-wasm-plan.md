# 0005: Browser MLS via Go-to-WASM harness

## Status
Accepted

## Context
- ROADMAP Phase 0 and MVP-3 call for MLS in browsers via WASM without introducing Rust.
- The Go MLS harness is the current source of truth for MLS flows (DM and conformance vectors) and is already vendored for offline builds.
- We need a path that keeps CLI/gateway/web interop aligned while avoiding toolchains that complicate offline reproducibility (e.g., cargo or system package installs).

## Decision
- Adopt a Go-to-WASM build of the existing MLS harness/library as the default browser MLS target.
- Reuse the same vendored Go dependencies and deterministic harness codepaths, compiled to WASM using the Go toolchain (TinyGo is acceptable if it reduces bundle size without changing language family).
- Expose a minimal JS/TypeScript wrapper that mirrors the CLI entry points (protect/unprotect, welcome/commit handling) so browser clients and the gateway exercise identical semantics.
- Keep builds offline-friendly: no Rust, no external downloads beyond the vendored Go modules; reuse the existing `-mod=vendor` workflow.

## Consequences
- Browser MLS behavior will stay in lockstep with the Go harness and gateway tests, reducing interop drift.
- Build pipelines must include a WASM artifact (Go compiler or TinyGo) and a small JS shim; test fixtures should reuse the harness vectors to validate protect/unprotect in the browser runtime.
- Follow-up work (Phase 5): integrate the WASM module into the web client skeleton, add browser-side MLS vector checks, and wire DM round-trips against the gateway using the shared harness contract.
- Risk: Go-to-WASM size/performance could lag native; mitigate by measuring bundle size, gating crypto operations behind wasm-safe APIs, and keeping deterministic vector tests in CI for both CLI and browser targets.
