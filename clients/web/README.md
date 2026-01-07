# Web client skeleton

This static demo exercises the gateway v1 WebSocket protocol without any build tooling or package manager dependencies. It is intentionally frameworkless (plain JS/HTML/CSS) to keep the supply chain small. Open `index.html` directly in a browser (or serve the directory with any static file server) to test session lifecycle and conversation operations. The MLS WASM verifier requires being served over HTTP (for example, `python -m http.server`) so that the browser can fetch `wasm_exec.js`, the harness module, and the vector JSON.

## Usage
1. Build the MLS harness WASM module: `tools/mls_harness/build_wasm.sh`. The generated `clients/web/vendor/mls_harness.wasm` is local-only and must not be committed.
2. Serve the directory over HTTP (for example, `python -m http.server`). Opening the HTML file directly will not work for WASM fetches.
3. Open `clients/web/index.html` in a modern browser. No npm/yarn/pnpm setup is required. The WASM vector check fetches artifacts under `clients/web/vendor/` and `clients/web/vectors/` from the static server started in the previous step.
4. Enter the gateway WebSocket URL (e.g. `ws://localhost:8787/v1/ws`).
5. Use **Start session** with an `auth_token` (and optional `device_id`/`device_credential`) to begin a session, or **Resume session** with a stored `resume_token`.
6. Subscribe to a conversation with **Subscribe**, optionally providing `from_seq` to replay missed events, acknowledge delivery with **Ack**, and send ciphertext with **Send ciphertext**.
7. Incoming `conv.event` entries are rendered with their ciphertext payload and any routing metadata (`conv_home`, `origin_gateway`). Heartbeat `ping` frames are answered automatically with `pong`.

## Supported gateway operations
- `session.start`
- `session.resume`
- `conv.subscribe` (supports `from_seq` for replay)
- `conv.ack`
- `conv.send`

## Frame envelope (gateway v1)
- Every WebSocket frame uses `{ v: 1, t, id, ts, body: { ... } }` with protocol fields in `body`.
- `session.start` expects `body.auth_token`, `body.device_id`, and `body.device_credential`.
- `session.resume` expects `body.resume_token` (returned by `session.ready`).
- `conv.subscribe` may include `body.from_seq` to replay from an earlier sequence (inclusive); omit to start at the live cursor.

## Notes
- All protocol keys and variables use snake_case to match gateway expectations.
- Payloads are treated as opaque ciphertext; MLS binding will be added in a later phase.
- Keep this demo self-contained and offline-friendly for CI and manual testing; no React/Vue or other frameworks are used or required.

## MLS DM (local) demo
1. Build the MLS WASM module (see steps above) and serve the directory over HTTP.
2. In the **MLS DM (local)** section, click **Create Alice** and **Create Bob** to generate deterministic participants.
3. Click **Init (Alice → Bob)** and **Join (Bob)**, then **Apply commit (Alice)** to finalize the handshake.
4. Enter plaintext in the Alice or Bob input and click the corresponding encrypt button to roundtrip encrypt/decrypt locally.
5. Use **Save to IndexedDB** and **Load from IndexedDB** to prove participant state survives reloads. **Reset local state** clears local state and IndexedDB records.

The DM demo uses local-only plaintext inputs/outputs for proof-of-life and does not send plaintext to the gateway. The WASM binary is generated locally and ignored by git; do not commit `clients/web/vendor/*.wasm`.

## Recommended CSP
- Baseline (no WASM yet):
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self' ws: wss:; base-uri 'self'; form-action 'self'`
  - The static files load without inline scripts or styles, and WebSocket connectivity is limited to the current origin plus explicit `ws:`/`wss:` endpoints.
- When adding the MLS WASM binding later, prefer extending `script-src` with `'wasm-unsafe-eval'` instead of enabling `unsafe-eval`.
