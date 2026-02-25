# Web client skeleton

This static web client is a protocol/interop harness for gateway v1 (WS flows, rooms helpers, DM harness, MLS vector checks, and a minimal social event viewer) without any build tooling or package manager dependencies. It is intentionally frameworkless (plain JS/HTML/CSS) to keep the supply chain small. It is **not** a product-grade Polycentric social+chat UI; the Social panel is intentionally a small scaffold for signed event inspection/debugging. Open `index.html` directly in a browser (or serve the directory with any static file server) to test session lifecycle and conversation operations. The MLS WASM verifier requires being served over HTTP (for example, `python -m http.server`) so that the browser can fetch `wasm_exec.js`, the harness module, and the vector JSON.

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
   - **Tip:** If a browser automation/forwarded-port session shows a blank `Not found` page, retry on an alternate local port (for example `python -m http.server 8765`) and open `/index.html` from that port.
   - **Automation tip:** prefer `http://127.0.0.1:<port>/index.html` (not hostnames rewritten by tooling) when capturing screenshots in containerized browser sessions.

### Screenshot sanity check (avoid blank Not Found captures)
- Confirm the served path with `curl -I` before taking the screenshot:
  - If serving from repo root: `curl -I http://127.0.0.1:<port>/<repo-root-web-path>/index.html`
  - If serving from `clients/web`: `curl -I http://127.0.0.1:<port>/index.html`
- Only capture once the response is `HTTP/1.0 200 OK` (or `HTTP/1.1 200 OK`).
- For browser-container captures, prefer an alternate local port (for example `8765`) and `127.0.0.1` URL forms to avoid forwarded-host rewrites that can produce false 404 pages.
- If automation shows **"Not found" in the top-left on a blank page**, treat it as a serving-path mismatch and re-run the capture against `http://127.0.0.1:8765/index.html` after confirming `curl -I` returns `200`.
- Known-good screenshot workflow (copy/paste): `python -m http.server 8765 --directory clients/web` then `curl -I http://127.0.0.1:8765/index.html` (expect `200`) before opening the page in browser automation.
3. Enter the gateway WebSocket URL (e.g. `ws://localhost:8787/v1/ws`).
4. Use **Start session** with an `auth_token` (and optional `device_id`/`device_credential`) to begin a session, or **Resume session** with a stored `resume_token`.
5. Subscribe to a conversation with **Subscribe**, optionally providing `from_seq` to replay missed events, acknowledge delivery with **Ack**, and send ciphertext with **Send ciphertext**.
6. Incoming `conv.event` entries are rendered with their ciphertext payload and any routing metadata (`conv_home`, `origin_gateway`). Heartbeat `ping` frames are answered automatically with `pong`.

## Social (Polycentric) panel
- The **Social (Polycentric)** fieldset fetches signed events with `GET /v1/social/events?user_id=...&limit=...` and renders `ts_ms`, `kind`, payload preview, `event_hash`, and `prev_hash`.
- Each rendered row includes **Use as DM peer**. Clicking it dispatches `social.peer.selected` and auto-fills the DM bootstrap `peer_user_id` input.
- `debug_etag` displays the response `ETag` header when present.

### Optional advanced publish path
- The panel includes an advanced/debug publish form that sends `POST /v1/social/events` with:
  - `kind`
  - `payload` (JSON)
  - `ts_ms`
  - `sig_b64` (manually pasted signature)
  - `prev_hash` (optional)
- The publish call uses `Authorization: Bearer <session_token>` from the existing `gateway.session.ready` event.
- Browser-side signing is intentionally out of scope for this static harness.

### Example flow (CLI publish → web view)
1. Start the gateway locally.
2. Publish a social post with CLI:
   - `python -m cli_app.hello social publish --kind post --payload '{"text":"hi"}' --gateway-url http://127.0.0.1:8787`
3. Open the web harness and start a gateway session.
4. In **Social (Polycentric)**, enter the same `user_id`, click **Fetch events**, and verify the post renders.
5. Click **Use as DM peer** and verify the DM bootstrap `peer_user_id` input is filled.

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
