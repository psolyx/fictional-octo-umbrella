# Web dependency policy and offline workflow

## Non-goals and guardrails
- No frameworks. The web client stays plain JS + HTML + CSS (Web Components allowed).
- No npm/yarn/pnpm in the critical path. The client must run from committed static assets.
- No bundlers or transpilers required to build or run the web client.
- No network-fetched dependencies at runtime beyond the gateway itself.

## Allowed dependency sources
- **Vendored static assets only.** Third-party JS/CSS utilities must be vendored under `clients/web/vendor/`.
- **Pin versions explicitly.** Record the upstream source, version, and license in the vendor file header or an adjacent README in `clients/web/vendor/`.
- **Prefer single-file drops.** Avoid dependency trees; do not introduce new package managers.
- **Review posture.** New vendored assets require a clear rationale and must remain compatible with the CSP in `clients/web/index.html`.

## Offline-friendly development workflow
1) **Serve static assets locally.** Use any static file server, for example:
   - `python -m http.server` from `clients/web/`
2) **Open the web UI.** Navigate to `http://localhost:8000/index.html`.
3) **Rebuild the WASM harness (no Node/npm).** Use the Go-to-WASM harness script:
   - `tools/mls_harness/build_wasm.sh`
   - Output: `clients/web/vendor/mls_harness.wasm`
4) **Commit policy for outputs.**
   - **Committed:** HTML, JS, CSS, `vendor/wasm_exec.js`, and vector fixtures under `clients/web/vectors/`.
   - **Not committed:** `clients/web/vendor/mls_harness.wasm` (local-only build artifact).

## CSP posture summary
- The CSP is defined inline in `clients/web/index.html` and must remain strict.
- `connect-src` includes `ws:` and `wss:` so WebSocket and EventSource/SSE connections work in modern browsers.
- WASM support uses `script-src 'self' 'wasm-unsafe-eval'` rather than `unsafe-eval`.

## Review checklist for web PRs
- [ ] No Node/npm, bundlers, or framework dependencies introduced.
- [ ] New third-party assets are vendored under `clients/web/vendor/` with pinned versions and license metadata.
- [ ] CSP in `clients/web/index.html` remains aligned with the asset and network requirements.
- [ ] Offline workflow still works with `python -m http.server` and a Go-only WASM build.
- [ ] No plaintext handling added; client stays ciphertext-only until MLS binding lands.
