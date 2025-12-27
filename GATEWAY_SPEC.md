# Gateway Spec (v1)

This document specifies the realtime gateway protocol and required server/client semantics.

## Editing rules (for Codex / no-touch iteration)
- Protocol message names (`t`) are stable API. Don’t rename; deprecate instead.
- Any new field must be optional and safely ignorable.
- Keep JSON examples valid and minimal.
- Normative keywords (MUST/SHOULD/MAY) apply only to gateway/client behavior.

---

## 1. Scope and roles

### 1.1 Scope
- Chat (MLS ciphertext transport)
- KeyPackage directory
- Offline delivery (store-and-forward)
- Presence (leases + watchlists)

### 1.2 Gateway role: MLS Delivery Service (DS)
The gateway implements DS responsibilities:
- directory for initial keying material (KeyPackages)
- routing MLS messages between clients
- sequencing policy for handshake safety (strongly-consistent ordering recommended)

(See References.)

---

## 2. Transport

### 2.1 WebSocket endpoint (primary)
- `wss://{gateway}/v1/ws`
- UTF-8 JSON frames.

### 2.2 SSE fallback (optional)
- `GET /v1/sse` (server -> client)
- `POST /v1/inbox` (client -> server)
Semantics match WS frames.

### 2.3 Caching requirements
- Any HTTP endpoints related to presence MUST return:
  - `Cache-Control: no-store`
- WS frames are not cached by CDNs; treat as realtime only.

---

## 3. Common framing

### 3.1 Client -> Server frame
```json
{
  "v": 1,
  "id": "c_01J...",
  "t": "conv.send",
  "ts": 1766793600123,
  "body": {}
}
