# Web client skeleton

This static web client is a protocol/interop harness for gateway v1 (WS flows, rooms helpers, DM harness, and MLS vector checks) without any build tooling or package manager dependencies. It is intentionally frameworkless (plain JS/HTML/CSS) to keep the supply chain small. It is **not** a product-grade Polycentric social+chat UI, and browser social feed/profile UI is not implemented in this repo yet. Open `index.html` directly in a browser (or serve the directory with any static file server) to test session lifecycle and conversation operations. The MLS WASM verifier requires being served over HTTP (for example, `python -m http.server`) so that the browser can fetch `wasm_exec.js`, the harness module, and the vector JSON.

## Usage
1. Build the MLS harness WASM module: `tools/mls_harness/build_wasm.sh`. The generated `clients/web/vendor/mls_harness.wasm` is local-only and must not be committed.
2. Serve the directory over HTTP (opening the HTML file directly will not work for WASM fetches). Pick one of the following options:
   - **Option A (serve from `clients/web`)**
     - `cd clients/web`
     - `python -m http.server`
     - `open http://localhost:8000/index.html`
   - **Option B (serve from repo root)**
     - `python -m http.server`
     - `open http://localhost:8000/clients/web/index.html`
   - **Preferred CSP dev server**
     - `python clients/web/tools/csp_dev_server.py --serve`
     - `open http://127.0.0.1:8081/index.html`
   - **Tip:** If you see a 404 for `/clients/web/...`, you likely started the server inside `clients/web/`; use `/index.html` instead.
   - **Tip:** The CSP dev server serves the `clients/web` directory root, so `/index.html` works while `clients/web/index.html` returns `Not found`.
3. Enter the gateway WebSocket URL (e.g. `ws://localhost:8787/v1/ws`).
4. Use **Start session** with an `auth_token` (and optional `device_id`/`device_credential`) to begin a session, or **Resume session** with a stored `resume_token`.
5. Subscribe to a conversation with **Subscribe**, optionally providing `from_seq` to replay missed events, acknowledge delivery with **Ack**, and send ciphertext with **Send ciphertext**.
6. Incoming `conv.event` entries are rendered with their ciphertext payload and any routing metadata (`conv_home`, `origin_gateway`). Heartbeat `ping` frames are answered automatically with `pong`.

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
The web client ships with a CSP enforced via `<meta http-equiv>` in `index.html`. The current policy string is:
`default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' ws: wss:; img-src 'self' data:; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`

### Meta CSP limitations
- HTTP response headers are preferred for CSP; `<meta http-equiv>` is acceptable for this static demo, but not every directive is enforced when delivered via meta.
- `frame-ancestors` is **not** enforced when CSP is delivered via `<meta http-equiv>`; to enforce it, configure the CSP header at your server/CDN.

### Why `connect-src` includes `ws:`/`wss:`
`connect-src` governs WebSocket and EventSource (SSE) endpoints. To allow realtime gateway connections, it must include `ws:`/`wss:` (in addition to the current origin).
