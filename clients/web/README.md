# Web client skeleton

This static demo exercises the gateway v1 WebSocket protocol without any build tooling or package manager dependencies. It is intentionally frameworkless (plain JS/HTML/CSS) to keep the supply chain small. Open `index.html` directly in a browser (or serve the directory with any static file server) to test session lifecycle and conversation operations.

## Usage
1. Open `clients/web/index.html` in a modern browser. No npm/yarn/pnpm setup is required.
2. Enter the gateway WebSocket URL (e.g. `ws://localhost:8787/v1/ws`).
3. Use **Start session** with an `auth_token` (and optional `device_id`/`device_credential`) to begin a session, or **Resume session** with a stored `resume_token`.
4. Subscribe to a conversation with **Subscribe**, optionally providing `from_seq` to replay missed events, acknowledge delivery with **Ack**, and send ciphertext with **Send ciphertext**.
5. Incoming `conv.event` entries are rendered with their ciphertext payload and any routing metadata (`conv_home`, `origin_gateway`). Heartbeat `ping` frames are answered automatically with `pong`.

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

## Recommended CSP
- Baseline (no WASM yet):
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self' ws: wss:; base-uri 'self'; form-action 'self'`
  - The static files load without inline scripts or styles, and WebSocket connectivity is limited to the current origin plus explicit `ws:`/`wss:` endpoints.
- When adding the MLS WASM binding later, prefer extending `script-src` with `'wasm-unsafe-eval'` instead of enabling `unsafe-eval`.
