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

### 3.4 Gateway discovery (v2 convention)
- `gateway_id` is opaque; federation deployments MUST provide a directory mapping `gateway_id` to a reachable base URL.
- The canonical resolution interface is `GET /v1/gateways/resolve?gateway_id=...` returning `{ "gateway_id": "...", "gateway_url": "https://..." }` for HTTP/WebSocket base URLs. Gateways MAY serve this locally or via an operator-distributed signed directory.
- In v1 single-gateway deployments clients typically connect directly and MAY ignore discovery, but v2 federation relies on this mapping; clients MUST treat absence of mapping data as a transient discovery error rather than assuming the connected gateway is authoritative.

#### 3.4.1 `/v1/gateways/resolve`
- **Request:** `GET /v1/gateways/resolve?gateway_id={id}`
- **Success (200):** `{"gateway_id": "{id}", "gateway_url": "https://..."}`
- **Client error (400):** missing or empty `gateway_id`
- **Not found (404):** directory does not contain the requested `gateway_id`
- This endpoint is safe to ignore for v1 single-gateway clients but is the discovery hook for v2 relay-to-home routing.

### 3.5 Social event log (append-only, CDN-cacheable reads)
- Social events are stored per-user as a single-head append-only chain. Forks are rejected: every event after the first MUST reference the current head via `prev_hash`; the first event MUST set `prev_hash` to `""` or `null`.
- Event fields:
  - `user_id`: Ed25519 public key encoded with URL-safe base64 (no padding).
  - `event_hash`: hex SHA-256 of the canonical bytes (see below).
  - `prev_hash`: empty string/`null` for the first event, otherwise the prior head’s `event_hash`.
  - `ts_ms`: event timestamp in milliseconds.
  - `kind`: opaque event type label (e.g., `post`).
  - `payload`: JSON object payload; it is normalized before signing to guarantee deterministic bytes.
  - `sig_b64`: Ed25519 signature over the canonical bytes, URL-safe base64 (no padding).
- Canonicalization for signing and hashing:
  - Normalize `payload` with `json.dumps(payload, separators=(",", ":"), sort_keys=True)` and parse it back to a JSON object to remove formatting noise.
  - Build a JSON object `{ "kind": kind, "payload": normalized_payload, "prev_hash": prev_hash or "", "ts_ms": ts_ms, "user_id": user_id }`, serialize it with `separators=(",", ":")` and `sort_keys=True`, and encode it as UTF-8. These bytes are signed and hashed.
  - `event_hash = hex(sha256(canonical_bytes))`. Servers MUST compute and persist this; clients SHOULD recompute to verify integrity.
- Endpoints:
  - `POST /v1/social/events`
    - Authenticated with `Authorization: Bearer {session_token}`.
    - Body: `{ prev_hash, ts_ms, kind, payload, sig_b64 }` (uses session-bound `user_id`).
    - Server MUST verify the signature against `user_id` (Ed25519), enforce the single-head rule, and persist `(user_id, event_hash, prev_hash, ts_ms, kind, payload_json, sig_b64)` append-only.
    - Duplicate publishes (same canonical bytes) MUST be idempotent: the gateway returns the existing event even if `prev_hash` no longer matches the current head, and duplicate rows are rejected.
    - Failure cases return `400 invalid_request` (bad signature, bad chain, oversized canonical event payload) or `401 unauthorized` (missing/expired session).
    - Gateways MUST enforce a per-user fixed-window publish limit (`GATEWAY_SOCIAL_PUBLISHES_PER_MIN`, default 30/min) before signature verification; exceeded requests return `429 rate_limited`.
    - Gateways MUST reject oversized canonical social events (`GATEWAY_MAX_SOCIAL_EVENT_BYTES`, default 65536) with `400 invalid_request` and message `social event too large`.
  - `GET /v1/social/events?user_id=...&limit=...&after_hash=...`
    - Returns `{ "events": [ {user_id, event_hash, prev_hash, ts_ms, kind, payload, sig_b64}, ... ] }` ordered from oldest after `after_hash`.
    - Responses MUST include `Cache-Control: public, max-age=30` and SHOULD include a strong validator (`ETag` based on the returned head hash and `Last-Modified` based on the newest `ts_ms`).
  - `GET /v1/social/profile?user_id=...&limit=...`
    - Returns a profile aggregate:
      ```json
      {
        "user_id": "u_...",
        "username": "alice",
        "description": "about text",
        "avatar": "https://...",
        "banner": "https://...",
        "interests": "music, coding",
        "friends": ["u_friend_1", "u_friend_2"],
        "latest_posts": [
          { "user_id": "u_...", "event_hash": "...", "ts_ms": 123, "kind": "post", "payload": {"value": "hello"}, "sig_b64": "..." }
        ]
      }
      ```
    - `limit` controls the maximum number of `latest_posts` returned (default `20`, max `100`).
    - Latest profile fields are last-writer-wins by `(ts_ms, event_hash)` among that user's signed events.
  - `GET /v1/social/feed?user_id=...&limit=...&cursor=...`
    - Returns followed-user + self posts:
      ```json
      {
        "items": [
          { "user_id": "u_...", "event_hash": "...", "ts_ms": 123, "kind": "post", "payload": {"value": "hello"} }
        ],
        "next_cursor": "123:event_hash_hex",
        "sources": ["u_self", "u_friend"]
      }
      ```
    - Ordering MUST be deterministic across backends:
      - primary sort: `ts_ms DESC`
      - tie-break for equal `ts_ms`: append order DESC (later appended events are newer)
    - `cursor` format is `ts_ms:event_hash`.
      - Cursor semantics are positional in the total order above.
      - Servers MAY resolve append-order tie-breaks via internal storage metadata (for example, row order/sequence lookup by `event_hash`).
      - If a cursor cannot be resolved to a known post at that timestamp, server MUST return `400 invalid_request` (`cursor not found`).
    - `next_cursor` is empty when there is no next page; otherwise it is derived from the oldest item in the current page under the deterministic order.

- Note: `kind` and signed append-only event semantics here are Polycentric-inspired, while this v1 gateway profile/feed API intentionally uses plain JSON (no protobuf requirement).

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
   - `user_id` is derived from `auth_token` (if it starts with `"Bearer "` the prefix is stripped; otherwise the raw token is used).
4. On success the server replies with `session.ready`:
   ```json
   {
     "v": 1,
     "t": "session.ready",
     "id": "s_01J...",
     "body": {
       "user_id": "u_01K...",
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

### 4.3 HTTP session endpoints (WS-optional)
- `POST /v1/session/start` mirrors the WS `session.start` body and returns the `session.ready.body` schema:
  ```http
  POST /v1/session/start
  Content-Type: application/json

  { "auth_token": "Bearer ey...", "device_id": "d_01G...", "device_credential": "b64" }
  ```
  Response:
  ```json
  {
    "user_id": "u_01K...",
    "session_token": "st_01J...",
    "resume_token": "rt_01J...",
    "expires_at": 1766797200123,
    "cursors": [ { "conv_id": "c_7N7...", "next_seq": 1025 } ]
  }
  ```
- `POST /v1/session/resume` accepts `{ "resume_token": "rt_..." }` and returns the same body as `session.ready` on success. On failure it returns `{ "code": "resume_failed", "message": "resume token invalid or expired" }`.

### 4.4 Gateway identity
- `gateway_id` names the gateway namespace used across routing metadata fields: `conv_home`, `origin_gateway`, `destination_gateway` (reserved hint), `served_by`, and `user_home_gateway`.
- `gateway_id` **MUST** be globally unique in federated deployments and **MUST** remain stable over time; rotating an identifier is considered an operationally breaking change.
- Every conversation is bound to a `conv_home` gateway when created; `conv_home` **MUST NOT** change for the lifetime of the conversation.
- Clients **MUST NOT** assume `origin_gateway == conv_home`. `conv_home` is the authoritative ordering identity even when the client is connected to another gateway; in current v1 single-gateway deployments these values will typically be equal.

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
- Each `conv_id` has a home gateway (`conv_home`) responsible for sequencing. `conv_home` **MUST** be assigned when the conversation is created and **MUST NOT** change for the lifetime of the conversation. In current v1 non-federated deployments, `conv_home` and `origin_gateway` will typically equal the connected gateway, but clients **MUST NOT** rely on this.
- `conv_home` selection is deterministic and immutable: rooms MUST assign `conv_home` to the creator's `user_home_gateway` at `POST /v1/rooms/create`; DMs MUST assign `conv_home` to the initiating sender's `user_home_gateway` when the DM is first created. If creation flows are received by a non-home gateway, the request MUST be relayed to the selected `conv_home` for sequencing authority in v2 relay-to-home.
- The accepting gateway is identified as `origin_gateway`; clients **MUST NOT** assume `origin_gateway == conv_home`. `destination_gateway` is a reserved client hint for future relay-to-home routing and is ignored in v1.
- The gateway stores an append-only log per `conv_id` containing:
  - `seq` (u64) assigned by the home gateway; values MUST be monotonically increasing by 1 per conversation.
  - `msg_id` (string) provided by the client; combined with `conv_id` it is the idempotency key.
  - `env` (opaque ciphertext envelope) containing the MLS wire message bytes.
- (conv_id, msg_id) MUST be idempotent: retries with the same pair MUST return the same `seq` and MUST NOT create duplicates.
- Delivery Service ordering: broadcasts MUST be emitted in `seq` order to all members, including the sender.
- Echo-before-apply (see ADR 0002): clients MUST NOT apply their own MLS Commit until the DS echoes it back with an assigned `seq`. The DS MUST echo to the sender as well as to other members.
- Discovery: v2 federation relies on directory resolution (see §3.4). Servers MAY include optional hints such as `gateway_url` or `conv_home_url` alongside routing metadata in responses; clients MUST treat them as hints and ignore them if absent and MUST rely on the directory mapping for authoritative resolution.

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
  - If `from_seq` is older than retained history, server MAY reject replay with `error.code = replay_window_exceeded`. `body.message` remains a human-readable compatibility string. Servers MAY additionally include optional structured fields `body.requested_from_seq`, `body.earliest_seq`, and `body.latest_seq` so clients can recover deterministically without string parsing.
  - Structured replay-window payload example (fields are additive/optional):
    ```json
    {
      "v": 1,
      "t": "error",
      "body": {
        "code": "replay_window_exceeded",
        "message": "requested_from_seq=1 earliest_seq=42",
        "requested_from_seq": 1,
        "earliest_seq": 42,
        "latest_seq": 84
      }
    }
    ```
  - Each delivered message uses `conv.event`:
    ```json
    {
      "v": 1,
      "t": "conv.event",
      "body": {
        "conv_id": "c_7N7...",
        "seq": 513,
        "msg_id": "m_01H...",
        "env": "base64-mls-ciphertext",
        "conv_home": "gw_01H...",
        "origin_gateway": "gw_01H..."
      }
    }
    ```
  - `conv_home` identifies the ordering authority for the conversation; `origin_gateway` is the gateway that accepted the send. In current v1 non-federated deployments they will typically match the connected gateway, but clients **MUST NOT** assume equality and **MUST** treat `conv_home` as authoritative even when connected elsewhere. Clients MUST ignore unknown fields.

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
      "env": "base64-mls-ciphertext",
      "destination_gateway": "gw_optional_hint"
    }
  }
  ```
- The server MUST NOT inspect plaintext; `env` is opaque.
- Clients MAY include `destination_gateway` as a routing hint for future relay-to-home federation; it is ignored in v1.
- On success the server replies with `conv.acked` including the assigned `seq` and routing metadata:
  ```json
  {
    "v": 1,
    "t": "conv.acked",
    "id": "c_send_01...",
    "body": {
      "conv_id": "c_7N7...",
      "msg_id": "m_01H...",
      "seq": 514,
      "conv_home": "gw_01H...",
      "origin_gateway": "gw_01H..."
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

### 7.6 SSE + HTTP inbox fallback
- Endpoint: `POST /v1/inbox` (HTTP) authenticated via `Authorization: Bearer {session_token}`.
  - Body wraps WS-equivalent frames:
    ```json
    { "v": 1, "t": "conv.send", "body": { "conv_id": "c_7N7...", "msg_id": "m_01H...", "env": "base64" } }
    ```
    ```json
    { "v": 1, "t": "conv.ack", "body": { "conv_id": "c_7N7...", "seq": 10 } }
    ```
    - Responses:
      - `conv.send` → `{ "status": "ok", "seq": <assigned_seq>, "conv_home": "gw_home_01...", "origin_gateway": "gw_edge_02..." }` (idempotent on retries). This explicitly shows a federated path where the accepting gateway (`origin_gateway`) is not the sequencing authority (`conv_home`).
      - `conv.ack` → `{ "status": "ok" }` after advancing the cursor (`next_seq = max(next_seq, seq+1)`).
  - Membership and idempotency invariants are identical to the WS transport.
- Endpoint: `GET /v1/sse` (HTTP, streaming) authenticated via `Authorization: Bearer {session_token}`.
  - Query params: `conv_id` (required), `from_seq` (optional inclusive start), `after_seq` (optional legacy; maps to `from_seq = after_seq + 1` when `from_seq` is omitted).
  - Membership MUST be enforced on connect and during the stream; revoked members stop receiving events and the stream closes.
  - Replay + live stream: server delivers `conv.event` starting at `from_seq` inclusive, then streams new events in `seq` order.
  - If requested `from_seq` was pruned by retention policy, server MAY return HTTP `410` with `{ "code": "replay_window_exceeded", "message": "requested history has been pruned", "earliest_seq": <int>, "latest_seq": <int> }`.
    - SSE wire format:
      ```
      event: conv.event
      data: {"v":1,"t":"conv.event","body":{"conv_id":"c_7N7...","seq":1,"msg_id":"m_01H...","env":"base64","sender_device_id":"d_01G...","conv_home":"gw_home_01...","origin_gateway":"gw_edge_02..."}}

      : ping
      ```
    - Keepalive comments (`: ping`) SHOULD be sent roughly every 15 seconds during idle periods.

---

## 8. Rooms (invite-only v1)
- Conversations are created explicitly via HTTP; until a room is created, all `conv.subscribe`/`conv.send` attempts MUST be rejected with `error.code = forbidden`.
- Membership is user-centric and multi-device aware. Roles:
  - `owner` (creator) MAY invite or remove other members and cannot be removed.
  - `admin` (optional) MAY invite or remove other members except the owner.
  - `member` has no governance permissions.
- Server MUST enforce membership for both streaming and persistence operations:
  - `conv.subscribe`/replay MUST return `error.forbidden` to non-members and MUST NOT deliver history.
  - `conv.send` MUST return `error.forbidden` to non-members and MUST NOT append or broadcast the payload.
  - For room conversations (`conv_id` does not start with `dm_`), room-muted members MUST receive `error.forbidden` with message `muted` when calling `conv.send`.
  - Gateways MUST enforce per-user-per-conversation fixed-window send limits (`GATEWAY_CONV_SENDS_PER_MIN`, default 120/min). Exceeding limits returns `rate_limited` (`429` on HTTP inbox, `error` frame on WS).
  - Gateways MUST reject oversized `env` payloads (`GATEWAY_MAX_ENV_B64_LEN`, default 262144 chars) with `400 invalid_request` and message `env too large`.
  - For 2-member DM conversations, if either user has blocked the other, `conv.send` MUST fail with `forbidden` and message `blocked`.
  - Active subscriptions MUST stop receiving `conv.event` once membership is revoked; servers SHOULD unsubscribe the device and MAY emit a one-time `{code: "forbidden", message: "membership revoked"}` error frame instead of closing the socket.
- Deterministic caps and rate limits (per conversation):
  - MAX_MEMBERS_PER_CONV: 1024 (server MAY reject above this cap using `limit_exceeded`).
  - INVITES_PER_MIN, REMOVES_PER_MIN: 60 per actor; excess MUST return `rate_limited`.

### 8.1 Create
- Endpoint: `POST /v1/rooms/create` (HTTP, authenticated via `Authorization: Bearer {session_token}`).
- Body:
  ```json
  {
    "conv_id": "c_7N7...",
    "members": ["u_01F...", "u_02F..."]
  }
  ```
- Semantics:
  - Creates the room with the caller as `owner` and adds optional initial members (owner is always included).
  - On success returns `{ "status": "ok" }`.
  - Errors: `invalid_request` (malformed payload or duplicate conversation), `limit_exceeded` (member cap).

### 8.1a List member conversations
- Endpoint: `GET /v1/conversations` (HTTP, authenticated as above).
- Response:
  ```json
  {
    "items": [
      {
        "conv_id": "c_7N7...",
        "role": "owner",
        "created_at_ms": 1766793600123,
        "home_gateway": "gw_local",
        "member_count": 2,
        "members": ["u_01F...", "u_02F..."],
        "earliest_seq": 4,
        "latest_seq": 27,
        "latest_ts_ms": 1766793920456,
        "last_read_seq": 26,
        "unread_count": 1
      }
    ]
  }
  ```
- Semantics:
  - Returns only conversations where the authenticated `user_id` is currently a member.
  - Ordering MUST be deterministic: `created_at_ms` ascending, then `conv_id` ascending.
  - `member_count` MUST always be present.
  - `members` SHOULD be included only when `member_count <= 20`; for larger rooms it MAY be omitted to keep responses bounded.
  - `earliest_seq`, `latest_seq`, and `latest_ts_ms` describe the currently retained conversation log bounds.
  - `last_read_seq` reports the authenticated member's retained read pointer for the conversation (`null` when unset).
  - `unread_count` reports deterministic unread messages as `max(0, latest_seq - max(last_read_seq, earliest_seq - 1, 0))`; when `latest_seq` is `null`, unread is `0`.
  - If a conversation has no retained log events, `earliest_seq`, `latest_seq`, and `latest_ts_ms` MUST be `null`.
  - `earliest_seq` MUST be the minimum retained `seq` (after retention pruning).
  - `latest_seq` MUST be the maximum retained `seq`.
  - `latest_ts_ms` MUST equal the `ts_ms` of the event at `latest_seq`.

### 8.1b Mark conversation read
- Endpoint: `POST /v1/conversations/mark_read` (HTTP, authenticated as above).
- Body:
  ```json
  {
    "conv_id": "c_7N7...",
    "to_seq": 27
  }
  ```
  - `to_seq` is optional. If omitted, the server marks read through the current retained `latest_seq` (or `0` when no events are retained).
- Response:
  ```json
  {
    "status": "ok",
    "conv_id": "c_7N7...",
    "last_read_seq": 27,
    "unread_count": 0
  }
  ```
- Semantics:
  - Membership is required. Non-members and unknown conversations MUST both return `403 forbidden`.
  - Marking read MUST be monotonic per (`conv_id`, `user_id`): `last_read_seq` MUST NOT decrease.
  - The effective minimum mark is clamped to `earliest_seq - 1` when retention has pruned older events.
  - `unread_count` MUST be deterministic and never negative.

### 8.1c DM create alias
- Endpoint: `POST /v1/dms/create` (HTTP, authenticated via `Authorization: Bearer {session_token}`).
- Body:
  ```json
  {
    "peer_user_id": "u_02F...",
    "conv_id": "dm_optional_id"
  }
  ```
- Semantics:
  - Thin alias over room creation for the DM-as-2-member-room model.
  - `peer_user_id` is required, MUST be non-empty, and MUST NOT equal the caller `user_id`.
  - If `conv_id` is omitted/empty, server generates a new DM conversation id and returns it.
  - Underlying creation path MUST match `POST /v1/rooms/create` semantics with exactly one peer member.
  - Success response includes room-create compatibility fields plus `conv_id`, e.g. `{ "status": "ok", "conv_id": "dm_..." }`.
  - Errors: `invalid_request` for invalid peer or invalid `conv_id`; `unauthorized` when auth is missing/invalid.
  - Gateways MUST enforce per-user DM-create fixed-window limits (`GATEWAY_DMS_CREATES_PER_MIN`, default 30/min) and return `429 rate_limited` on exceed.
  - DM create MUST return `403 forbidden` with message `blocked` if either side has blocked the other.

### 8.2 Invite
- Endpoint: `POST /v1/rooms/invite` (HTTP, authenticated as above).
- Body:
  ```json
  {
    "conv_id": "c_7N7...",
    "members": ["u_03F...", "u_04F..."]
  }
  ```
- Semantics:
  - Only owners/admins may invite; unauthorized callers receive `forbidden`.
  - Invites MUST respect per-actor invite rate limits and the overall member cap (errors: `rate_limited`, `limit_exceeded`).
  - Invites MUST return `403 forbidden` with message `blocked` when inviter/target blocklists conflict.
  - Invites MUST return `403 forbidden` with message `banned` when any target is room-banned.
  - Success response: `{ "status": "ok" }`.

### 8.3 Remove
- Endpoint: `POST /v1/rooms/remove` (HTTP, authenticated as above).
- Body:
  ```json
  {
    "conv_id": "c_7N7...",
    "members": ["u_03F...", "u_04F..."]
  }
  ```
- Semantics:
  - Only owners/admins may remove; removing the owner MUST be rejected (`forbidden`).
  - Rate limited per actor per conversation (errors: `rate_limited`).
  - Success response: `{ "status": "ok" }`.

### 8.4 Promote admin
- Endpoint: `POST /v1/rooms/promote` (HTTP, authenticated as above).
- Body:
  ```json
  {
    "conv_id": "c_7N7...",
    "members": ["u_03F...", "u_04F..."]
  }
  ```
- Semantics:
  - Only the `owner` may promote.
  - Promoting a non-member is a no-op; the owner cannot be demoted or re-labeled.
  - Success response: `{ "status": "ok" }`; errors: `forbidden`, `invalid_request` for malformed payloads.

### 8.5 Demote admin
- Endpoint: `POST /v1/rooms/demote` (HTTP, authenticated as above).
- Body matches promote.
- Semantics:
  - Only the `owner` may demote; demoting non-admins is a no-op.
  - The owner role is immutable and MUST NOT be changed.
  - Success response: `{ "status": "ok" }`; errors: `forbidden`, `invalid_request` for malformed payloads.

### 8.6 Ban / unban and ban listing
- Endpoint: `POST /v1/rooms/ban` (HTTP, authenticated as above).
- Body:
  ```json
  {
    "conv_id": "c_7N7...",
    "members": ["u_03F...", "u_04F..."]
  }
  ```
- Semantics:
  - Only owners/admins may ban; banning the owner is ignored.
  - Ban MUST remove the target from current room membership if present and persist `(conv_id, user_id)` in the room banlist.
  - Banned targets MUST be rejected from subsequent `POST /v1/rooms/invite` attempts with `403 forbidden` and message `banned`.
  - Success response: `{ "status": "ok" }`; errors: `forbidden`, `invalid_request` for malformed payloads.

- Endpoint: `POST /v1/rooms/unban` (HTTP, authenticated as above).
- Body matches ban.
- Semantics:
  - Only owners/admins may unban.
  - Unban removes the persisted ban entry; it does not re-add membership automatically.
  - Success response: `{ "status": "ok" }`; errors: `forbidden`, `invalid_request` for malformed payloads.

- Endpoint: `GET /v1/rooms/bans?conv_id=...` (HTTP, authenticated as above).
- Response:
  ```json
  {
    "conv_id": "c_7N7...",
    "bans": [
      {
        "user_id": "u_03F...",
        "banned_by_user_id": "u_01F...",
        "banned_at_ms": 1766793600123
      }
    ]
  }
  ```
- Semantics:
  - Visibility is admin-only (`owner`/`admin`). Non-admin members and non-members MUST receive `403 forbidden`.
  - Results MUST be deterministic and sorted by `user_id` ascending.
  - `banned_at_ms` MUST be serialized as an integer epoch-ms value.

### 8.7 Mute / unmute and mute listing
- Endpoint: `POST /v1/rooms/mute` (HTTP, authenticated as above).
- Body:
  ```json
  {
    "conv_id": "c_7N7...",
    "members": ["u_03F...", "u_04F..."]
  }
  ```
- Semantics:
  - `conv_id` values starting with `dm_` MUST be rejected with `400 invalid_request` and message `not a room`.
  - Only owners/admins may mute; muting the owner is ignored.
  - Mute does not remove membership and does not change roles.
  - Muted users MUST receive `403 forbidden` and message `muted` when sending `conv.send` in that room.
  - Success response: `{ "status": "ok" }`; errors: `forbidden`, `invalid_request` for malformed payloads.

- Endpoint: `POST /v1/rooms/unmute` (HTTP, authenticated as above).
- Body matches mute.
- Semantics:
  - `conv_id` values starting with `dm_` MUST be rejected with `400 invalid_request` and message `not a room`.
  - Only owners/admins may unmute.
  - Success response: `{ "status": "ok" }`; errors: `forbidden`, `invalid_request` for malformed payloads.

- Endpoint: `GET /v1/rooms/mutes?conv_id=...` (HTTP, authenticated as above).
- Response:
  ```json
  {
    "conv_id": "c_7N7...",
    "mutes": [
      {
        "user_id": "u_03F...",
        "muted_by_user_id": "u_01F...",
        "muted_at_ms": 1766793600123
      }
    ]
  }
  ```
- Semantics:
  - `conv_id` values starting with `dm_` MUST be rejected with `400 invalid_request` and message `not a room`.
  - Visibility is admin-only (`owner`/`admin`). Non-admin members and non-members MUST receive `403 forbidden`.
  - Results MUST be deterministic and sorted by `user_id` ascending.
  - `muted_at_ms` MUST be serialized as an integer epoch-ms value.


---

## 9. KeyPackage directory APIs (gateway-hosted v1)
- Base path: `/v1/keypackages` (HTTP, authenticated via `session_token` or equivalent bearer).
- MLS-aligned deployments MAY reserve an application-specific KeyPackage extension to advertise `user_home_gateway` or other gateway discovery hints; v1 clients/servers MUST ignore the extension if present and the field MUST remain optional.

### 9.1 Publish
- Endpoint: `POST /v1/keypackages`
- Body:
  ```json
  {
    "device_id": "d_01G...",
    "keypackages": ["base64-mls-keypackage-1", "base64-mls-keypackage-2"]
  }
  ```
- Server MUST store one-time-use KeyPackages, enforce device ownership, and MAY cap pool size per device.
- Requests MUST be authenticated for the publishing user and device; the server associates published material with both `user_id` and `device_id`.
- Requests MAY include routing hints such as `destination_gateway` or `user_home_gateway` for future proxying; they are ignored in v1.
- Response: `{ "status": "ok", "served_by": "gw_edge_02...", "user_home_gateway": "gw_home_01..." }` to highlight that KeyPackage storage/serving may occur on a gateway different from the user's home authority.

### 9.2 Fetch
- Endpoint: `POST /v1/keypackages/fetch`
- Body:
  ```json
  {
    "user_id": "u_01F...",
    "count": 2
  }
  ```
- Server returns up to `count` available KeyPackages for the requested user across all of their devices and MUST rate limit fetches.
- Requests MAY include routing hints such as `destination_gateway` or `user_home_gateway` for future proxying; they are ignored in v1.
- Response: `{ "keypackages": [ ... ], "served_by": "gw_edge_02...", "user_home_gateway": "gw_home_01..." }` (clients MUST treat `user_home_gateway` as authoritative even when `served_by` differs).

### 9.3 Rotate / Revoke
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
- Requests MUST be authenticated for the owning user; rotate only affects the provided `device_id` under that user.
- Requests MAY include routing hints such as `destination_gateway` or `user_home_gateway` for future proxying; they are ignored in v1.
- Response mirrors publish: `{ "status": "ok", "served_by": "gw_edge_02...", "user_home_gateway": "gw_home_01..." }`.

### 9.4 Rate limits and “last resort”
- Directory endpoints MUST be rate-limited per device/user to prevent scraping and to conserve pool health. `/v1/keypackages/fetch` MUST enforce a deterministic fixed-window limit (per requesting user across devices) of at least 60 fetches per minute and return `429 rate_limited` when exceeded. Operators MAY apply stricter quotas to publish/rotate as needed.
- Operators SHOULD maintain a minimum pool size alert and MAY allow a temporary bypass (“last resort”) for emergency replenishment when a device runs out of usable KeyPackages.

---

## 10. Presence (ephemeral lease model)
- All presence endpoints MUST include `Cache-Control: no-store` and responses MUST NOT be cached by intermediaries or clients.
- Presence APIs MUST be rate-limited at the application layer.
- Presence watchlists are keyed by `user_id`; mutual watch gating is evaluated at the user level.
- Presence blocklists are user-level and symmetric: if either side blocks the other, presence updates MUST NOT be delivered in either direction.
- A user is considered online if any of their devices has a non-expired, non-invisible lease; offline only when all visible leases expire or turn invisible. `expires_at` reflects the latest visible lease expiry.
- Presence updates MUST fan out to all active devices for an eligible watcher user.
- Lease TTLs MUST be clamped server-side to a minimum of 15 seconds and a maximum of 300 seconds.
- Until Polycentric contact graphs are available, delivery MUST be gated by mutual watch: a watcher only receives updates if the target's watchlist includes the watcher.

### 10.1 Lease and renew
- Endpoint: `POST /v1/presence/lease`
- Body:
  ```json
  {
    "device_id": "d_01G...",
    "ttl_seconds": 120
  }
  ```
- Server grants a lease (soft-state) and returns an expiry timestamp. Clients MUST renew via `POST /v1/presence/renew` before expiry.

### 10.2 Watch / unwatch
- Endpoint: `POST /v1/presence/watch`
- Body:
  ```json
  {
    "contacts": ["u_01F...", "u_02F..."]
  }
  ```
- The watchlist is contacts-only; server MUST enforce caps per watcher and per target.
- To remove entries use `POST /v1/presence/unwatch` with the same schema.
- Attempts to watch a blocked contact MUST be ignored or rejected; blocked pairs MUST NOT receive updates even if mutual watch exists.

### 10.3 Block / unblock
- Endpoint: `POST /v1/presence/block`
- Body:
  ```json
  {
    "contacts": ["u_01B...", "u_02B..."]
  }
  ```
- Endpoint: `POST /v1/presence/unblock` (same schema)
- Blocking is user-centric and multi-device aware. If either participant blocks the other, presence updates MUST NOT be delivered in either direction, including in mutual-watch cases. Servers MAY silently ignore blocked targets when processing watch requests. Responses SHOULD include the current blocked count for the caller.
- Endpoint: `GET /v1/presence/blocklist` (authenticated) returns `{ "blocked": ["u_...", ...] }` for the caller only; list order MUST be deterministic (sorted ascending).

### 10.4 Presence updates
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

### 10.5 Status bootstrap (privacy-safe)
- Endpoint: `POST /v1/presence/status`
- Body:
  ```json
  {
    "contacts": ["u_01F...", "u_02F..."]
  }
  ```
- Response:
  ```json
  {
    "statuses": [
      {"user_id": "u_01F...", "status": "online", "expires_at": 1766793650123, "last_seen_bucket": "now"},
      {"user_id": "u_02F...", "status": "unavailable", "expires_at": 1766793650123, "last_seen_bucket": "7d"}
    ]
  }
  ```
- Authorization is required.
- Eligibility MUST match the same access-control rule as `presence.update` fanout (mutual watch + blocklist enforcement in v1).
- Ineligible or blocked contacts MUST return `status: "unavailable"`.
- Results MUST be deterministic: de-duplicated and sorted by `user_id`.

### 10.5 SSE/WS consumption
- Presence updates MAY be delivered on the same WS connection as conversations or via SSE.
- `presence.watch` and `presence.unwatch` MAY be invoked over WS frames with the same bodies.
- Presence data MUST NOT be persisted or cached beyond the lease TTL by clients.

---

## 11. References
- ADR 0002 — Sequencing, idempotency, and echo-before-apply invariants.
- MLS Delivery Service responsibilities are described in ARCHITECTURE.md.
