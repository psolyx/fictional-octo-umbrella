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

## 2. Versioning and compatibility
- All frames include `"v": 1` for this specification.
- Unknown fields MUST be ignored by both clients and servers when `v=1` so additive changes remain backward compatible.
- A peer receiving an unsupported `v` MAY close the connection with an `error` frame indicating `unsupported_version`.

---

## 3. Transport

### 3.1 WebSocket endpoint (primary)
- `wss://{gateway}/v1/ws`
- UTF-8 JSON frames.

### 3.2 SSE fallback (optional)
- `GET /v1/sse` (server -> client)
- `POST /v1/inbox` (client -> server)
Semantics match WS frames.

### 3.3 Caching requirements
- Any HTTP endpoints related to presence MUST return:
  - `Cache-Control: no-store`
- WS frames are not cached by CDNs; treat as realtime only.

---

## 4. Authentication and session lifecycle

### 4.1 Initial handshake (WS)
1. Client opens the WebSocket.
2. Client MUST send `session.start` as the first frame containing:
   ```json
   {
     "v": 1,
     "t": "session.start",
     "id": "c_01J...",
     "body": {
       "auth_token": "Bearer ey...",       
       "device_id": "d_01G...",             
       "device_credential": "MLS-credential-bytes-base64"
     }
   }
   ```
3. Server validates the authentication token and binds it to `device_id` and the presented MLS credential.
4. On success the server replies with `session.ready`:
   ```json
   {
     "v": 1,
     "t": "session.ready",
     "id": "s_01J...",
     "body": {
       "session_token": "st_01J...",
       "resume_token": "rt_01J...",
       "expires_at": 1766797200123,
       "cursors": [
         { "conv_id": "c_7N7...", "next_seq": 1025 },
         { "conv_id": "c_9X9...", "next_seq": 8 }
       ]
     }
   }
   ```
   - `session_token` MUST be presented on subsequent writes (e.g., `Authorization: Session st_...` header for HTTP inbox).
   - `resume_token` MUST allow lossless reconnection without repeating authentication while it remains valid.
   - `cursors` describes persisted per-device replay positions used as defaults for subscriptions.
   - Each entry is `{conv_id, next_seq}` where `next_seq` is the next server-assigned seq the device SHOULD request (inclusive replay).
   - If the server has no stored cursor for a conversation, the implicit default is `next_seq = 1`.
   - Monotonicity: for a given (`device_id`, `conv_id`), `next_seq` MUST NOT decrease across responses.
   - Back-compat: the field MAY be omitted; if omitted, clients must treat it as an empty list (no disclosure), and server-side cursor state is unchanged by omission.
5. On authentication failure the server responds with `error` and closes the connection.

### 4.2 Resume flow
- When reconnecting, the client SHOULD send `session.resume` as the first frame:
  ```json
  {
    "v": 1,
    "t": "session.resume",
    "id": "c_02J...",
    "body": {
      "resume_token": "rt_01J..."
    }
  }
  ```
- If the resume token is valid and within expiry, the server MUST accept it without re-authentication and reply with `session.ready` including a fresh `resume_token` and `cursors` as defined above.
- If the resume token is invalid or expired, the server MUST respond with `error` (`resume_failed`) and require a new `session.start`.
- A server MAY bound resume age; clients MUST be prepared to re-authenticate when requested.
- Clients use the returned `cursors` as the default replay position when later sending `conv.subscribe` without `from_seq`.
- Deprecated legacy cursor compatibility: servers MAY accept `session.resume.body.cursor` as a best-effort hint shaped like `{ "conv_id": "...", "after_seq": <int> }` (or `seq` defined as `after_seq`). This hint is exclusive and maps to `from_seq = after_seq + 1`, is optional, and MUST NOT regress stored cursors.

---

## 5. Framing

### 5.1 Client -> Server frame
```json
{
  "v": 1,
  "id": "c_01J...",
  "t": "conv.send",
  "ts": 1766793600123,
  "body": {}
}
```
- `id`: client-generated request identifier used for correlation.
- `ts`: client timestamp in ms since epoch; used for observability only.

### 5.2 Server -> Client frame
```json
{
  "v": 1,
  "t": "conv.event",
  "body": {}
}
```
- Server response frames MAY omit `id` for unsolicited events (deliveries, presence updates).
- Unknown fields MUST be ignored.

---

## 6. Conversation model and sequencing
- `conv_id` MUST be the MLS `group_id` (32 random bytes, base64/URL-safe encoded).
- Room membership is invite-only for v1. The DS MUST enforce membership on every send and replay; non-members receive `error`=`forbidden`.
- DMs are represented as 2-person MLS groups with the same `conv_id` rules.
- The gateway stores an append-only log per `conv_id` containing:
  - `seq` (u64) assigned by the gateway; values MUST be monotonically increasing by 1 per conversation.
  - `msg_id` (string) provided by the client; combined with `conv_id` it is the idempotency key.
  - `env` (opaque ciphertext envelope) containing the MLS wire message bytes.
- (conv_id, msg_id) MUST be idempotent: retries with the same pair MUST return the same `seq` and MUST NOT create duplicates.
- Delivery Service ordering: broadcasts MUST be emitted in `seq` order to all members, including the sender.
- Echo-before-apply (see ADR 0002): clients MUST NOT apply their own MLS Commit until the DS echoes it back with an assigned `seq`. The DS MUST echo to the sender as well as to other members.

---

## 7. Core messaging flows (WS/SSE)

### 7.1 Subscribe and replay
- Clients subscribe per conversation using `conv.subscribe`:
  ```json
  {
    "v": 1,
    "t": "conv.subscribe",
    "id": "c_sub_01...",
    "body": {
      "conv_id": "c_7N7...",
      "from_seq": 512
    }
  }
  ```
  - `from_seq` OPTIONAL: when provided, server MUST replay from `from_seq` (inclusive) subject to replay window; otherwise server resumes from the stored cursor (`next_seq`) for this device as last surfaced in `session.ready` (default 1).
- Legacy example (deprecated):
  ```json
  {
    "v": 1,
    "t": "conv.subscribe",
    "id": "c_sub_legacy_01...",
    "body": {
      "conv_id": "c_7N7...",
      "after_seq": 511
    }
  }
  ```
  - `after_seq` OPTIONAL, DEPRECATED: exclusive cursor hint; server maps to `from_seq = after_seq + 1`.
  - If both `from_seq` and `after_seq` are provided, `from_seq` wins.
- Server behavior:
  - Validate membership; reject with `error` if unauthorized.
  - Perform bounded replay (implementation-defined window) and then stream new events.
  - Each delivered message uses `conv.event`:
    ```json
    {
      "v": 1,
      "t": "conv.event",
      "body": {
        "conv_id": "c_7N7...",
        "seq": 513,
        "msg_id": "m_01H...",
        "env": "base64-mls-ciphertext"
      }
    }
    ```

### 7.2 Ack / cursor advance
- Clients acknowledge progress with `conv.ack` (per device cursor):
  ```json
  {
    "v": 1,
    "t": "conv.ack",
    "id": "c_ack_01...",
    "body": {
      "conv_id": "c_7N7...",
      "seq": 513
    }
  }
  ```
- The gateway MUST persist per (`device_id`, `conv_id`) acknowledged progress as a cursor stored as `next_seq`.
- Acknowledging `seq = N` advances stored `next_seq` to at least `N + 1`, monotonically.
- The stored `next_seq` is used to resume after reconnect (including during `session.resume`).

### 7.3 Send
- Clients send ciphertext envelopes with `conv.send`:
  ```json
  {
    "v": 1,
    "t": "conv.send",
    "id": "c_send_01...",
    "body": {
      "conv_id": "c_7N7...",
      "msg_id": "m_01H...",
      "env": "base64-mls-ciphertext"
    }
  }
  ```
- The server MUST NOT inspect plaintext; `env` is opaque.
- On success the server replies with `conv.acked` including the assigned `seq`:
  ```json
  {
    "v": 1,
    "t": "conv.acked",
    "id": "c_send_01...",
    "body": {
      "conv_id": "c_7N7...",
      "msg_id": "m_01H...",
      "seq": 514
    }
  }
  ```
- If the send corresponds to a retry with an existing (`conv_id`, `msg_id`), the server MUST return the existing `seq` and MUST
  NOT emit an additional `conv.event`.

### 7.4 Errors
- Errors use a standard `error` frame:
  ```json
  {
    "v": 1,
    "t": "error",
    "id": "c_send_01...",
    "body": {
      "code": "forbidden",
      "message": "device not a member of conversation"
    }
  }
  ```
- Stable error codes include (non-exhaustive):
  - `unauthorized`, `resume_failed`, `forbidden`, `invalid_request`, `not_found`, `rate_limited`, `unsupported_version`, `internal_error`.
- Servers SHOULD close the connection after fatal errors (auth failures); otherwise they MAY keep it open.

### 7.5 Heartbeats
- The gateway SHOULD emit `ping` frames during idle periods (server -> client) and expect a `pong` reply:
  ```json
  { "v": 1, "t": "ping" }
  { "v": 1, "t": "pong" }
  ```
- Clients MAY proactively send `ping` to measure liveness.
- Idle timeout guidance: servers SHOULD close connections after 2× missed heartbeats; clients MUST re-resume using the latest `resume_token`.

---

## 8. KeyPackage directory APIs (gateway-hosted v1)
- Base path: `/v1/keypackages` (HTTP, authenticated via `session_token` or equivalent bearer).

### 8.1 Publish
- Endpoint: `POST /v1/keypackages`
- Body:
  ```json
  {
    "device_id": "d_01G...",
    "keypackages": ["base64-mls-keypackage-1", "base64-mls-keypackage-2"]
  }
  ```
- Server MUST store one-time-use KeyPackages, enforce device ownership, and MAY cap pool size per device.

### 8.2 Fetch
- Endpoint: `POST /v1/keypackages/fetch`
- Body:
  ```json
  {
    "user_id": "u_01F...",
    "count": 2
  }
  ```
- Server returns up to `count` available KeyPackages for the requested user and MUST rate limit fetches.

### 8.3 Rotate / Revoke
- Endpoint: `POST /v1/keypackages/rotate`
- Body:
  ```json
  {
    "device_id": "d_01G...",
    "revoke": true,
    "replacement": ["base64-mls-keypackage-new"]
  }
  ```
- Revocation is best-effort: server SHOULD prevent future fetch of revoked material but previously delivered KeyPackages MAY still be used by peers.

### 8.4 Rate limits and “last resort”
- Directory endpoints MUST be rate-limited per device/user to prevent scraping and to conserve pool health.
- Operators SHOULD maintain a minimum pool size alert and MAY allow a temporary bypass (“last resort”) for emergency replenishment when a device runs out of usable KeyPackages.

---

## 9. Presence (ephemeral lease model)
- All presence endpoints MUST include `Cache-Control: no-store` and responses MUST NOT be cached by intermediaries or clients.
- Presence APIs MUST be rate-limited at the application layer.
- Lease TTLs MUST be clamped server-side to a minimum of 15 seconds and a maximum of 300 seconds.
- Until Polycentric contact graphs are available, delivery MUST be gated by mutual watch: a watcher only receives updates if the target's watchlist includes the watcher.

### 9.1 Lease and renew
- Endpoint: `POST /v1/presence/lease`
- Body:
  ```json
  {
    "device_id": "d_01G...",
    "ttl_seconds": 120
  }
  ```
- Server grants a lease (soft-state) and returns an expiry timestamp. Clients MUST renew via `POST /v1/presence/renew` before expiry.

### 9.2 Watch / unwatch
- Endpoint: `POST /v1/presence/watch`
- Body:
  ```json
  {
    "contacts": ["u_01F...", "u_02F..."]
  }
  ```
- The watchlist is contacts-only; server MUST enforce caps per watcher and per target.
- To remove entries use `POST /v1/presence/unwatch` with the same schema.

### 9.3 Presence updates
- Presence events are delivered as `presence.update` frames:
  ```json
  {
    "v": 1,
    "t": "presence.update",
    "body": {
      "user_id": "u_01F...",
      "status": "online",
      "expires_at": 1766793650123,
      "last_seen_bucket": "5m"
    }
  }
  ```
- Status is lease-based; absence of renewal implies expiration.
- “Invisible mode” hides a user from watchers except whitelisted contacts; server MUST suppress updates accordingly.
- `last_seen_bucket` is coarse (e.g., `now`, `5m`, `1h`, `1d`, `7d`).

### 9.4 SSE/WS consumption
- Presence updates MAY be delivered on the same WS connection as conversations or via SSE.
- `presence.watch` and `presence.unwatch` MAY be invoked over WS frames with the same bodies.
- Presence data MUST NOT be persisted or cached beyond the lease TTL by clients.

---

## 10. References
- ADR 0002 — Sequencing, idempotency, and echo-before-apply invariants.
- MLS Delivery Service responsibilities are described in ARCHITECTURE.md.
