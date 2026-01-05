# Architecture

This repo implements a Polycentric-based social platform with a separate realtime gateway for E2EE chat (MLS) and presence.

## Editing rules (for Codex / no-touch iteration)
- Keep top-level headings stable.
- Prefer additive changes. If you must change semantics, update the "Decisions" and "Risks" sections.
- Protocol details live in `GATEWAY_SPEC.md`; roadmap lives in `ROADMAP.md`.
- Use MUST/SHOULD/MAY only for protocol invariants.

### Decision and risk tracking
- Architecture decisions are logged in [DECISIONS.md](DECISIONS.md) with ADRs stored under `decisions/`.
- Active risks and proof tests are tracked in [RISK_REGISTER.md](RISK_REGISTER.md).

---

## 1. Goals

1) Polycentric-compatible social layer (identity + social feed/event log) with CDN-friendly HTTP queries.  
2) First-class CLI/TUI client plus web UI.  
3) Realtime chat: **E2EE rooms + E2EE 1:1 DMs**, both using **MLS everywhere** (DM = 2-member MLS group).  
4) Presence: real-time ephemeral soft state, privacy-preserving, CDN-proxied for protection.  
5) Self-host friendly behind “any CDN”, with first-class compatibility with Cloudflare.

## 2. Non-goals (v1)
- Federation between gateways.
- Public/discoverable rooms.
- Metadata padding/batching beyond basic abuse controls.
- Typing indicators.

---

## 3. System overview

### 3.1 Components
1) **Social Layer (Polycentric)**
   - Identity: Polycentric “system public key” identifies a user identity.
   - Content: append-only signed events, queried via HTTP APIs intended to be CDN-friendly/cacheable.
   - Clients use polycentric-core (TypeScript) as the canonical implementation.

2) **Realtime Layer (Gateway)**
   - WebSocket-first, SSE fallback.
   - Handles:
     - MLS Delivery Service roles: KeyPackage directory + message routing.
     - Ciphertext store-and-forward (mailboxes).
     - Presence leases + watchlists.

3) **Clients**
   - **CLI/TUI** (primary MVP): Polycentric social + chat + presence.
   - **Web UI** (later): reuse polycentric-web where possible; bolt on chat via same gateway.

### 3.2 Trust boundaries
- Polycentric servers store and serve signed social events. They can be untrusted for confidentiality; signatures provide integrity and origin authentication.
- Gateway stores/forwards **ciphertext only** for chat; it is not trusted with plaintext.
- Gateway can still observe metadata (connections, traffic patterns, membership if you choose to store it server-side).

---

## 4. Key architectural decisions

### 4.1 Separate “cache-friendly social” vs “uncacheable realtime”
- Polycentric HTTP API stays CDN-cache-friendly for feeds/profiles/topics.
- Chat + presence go through realtime gateway; **never cache** presence endpoints (`Cache-Control: no-store`) and WS is inherently non-cacheable.

### 4.2 MLS everywhere (rooms and DMs)
- Rooms and DMs are MLS groups.
- DM = MLS group of size 2.
- Gateway acts as an MLS Delivery Service (DS) and directory.

### 4.3 Strongly-consistent per-conversation ordering at the gateway
- Gateway assigns a monotonically increasing `seq` per conversation and broadcasts in that order.
- Clients apply handshake messages (Commits) in the delivered order and **do not apply their own Commit until it is echoed back** (prevents easy group forks).

Rationale: MLS architecture guidance explicitly describes a strongly-consistent “ordering server” DS and recommends “wait to apply your Commit until it’s broadcast back.” (See References.)

### 4.4 Default storage choices (v1)
- **KeyPackage distribution**: gateway-hosted directory.
- **Ciphertext persistence**: gateway stores conversation logs (store-and-forward).
- **Rooms**: invite-only.
- **Presence**: contacts-only subscriptions + TTL leases; coarse “last seen”.

---

## 5. Data model (conceptual)

### 5.1 Identities
- `user_id`: Polycentric system public key (stable identity).
- `device_id`: per-device identifier bound to an MLS credential.
- A user may have multiple devices.

### 5.2 Conversations
- `conv_id` = MLS `group_id` (random 32 bytes encoded). Used for both DMs and rooms.
- Room membership is expressed by MLS state; server may store an application-level member list for access control and abuse handling.

### 5.3 Messages
- Gateway stores an append-only per-conversation log:
  - `seq` (u64): server-assigned order
  - `msg_id`: client idempotency key
  - `env`: opaque envelope containing MLS wire message bytes

### 5.4 Gateway identity and routing metadata
- Each deployment advertises a stable `gateway_id` (default `gw_local` in dev/test; overridable via `GATEWAY_ID`).
- Every conversation is bound to a `conv_home` gateway that assigns `seq`; in v1 this is always the connected gateway.
- Requests surface the accepting `origin_gateway` (equals `conv_home` in v1) and reserve `destination_gateway` as a future hint for relay-to-home federation.
- Responses for conversation events and KeyPackage APIs include `conv_home`/`origin_gateway` or `served_by`/`user_home_gateway` to avoid ossifying single-gateway assumptions.

### 5.5 Presence
- Presence is a **lease** (soft state) with TTL, renewed periodically.
- Watchers subscribe to a bounded watchlist; server enforces authorization and rate limits.

---

## 6. Realtime gateway responsibilities

### 6.1 MLS Delivery Service functions
- KeyPackage upload and retrieval.
- Route MLS messages.
- Provide strongly-consistent sequencing for handshake messages (and optionally all messages).

### 6.2 Mailbox / offline delivery
- Store-and-forward ciphertext log.
- Resume semantics via per-device ack cursors.

### 6.3 Presence
- Lease-based online status.
- Coarse last-seen buckets.
- “Invisible mode” support.

### 6.4 Abuse controls (must be app-layer)
- CDN WAF applies to the initial WS upgrade; after upgrade, message frames are not inspected.
- Therefore the gateway MUST implement:
  - per-device rate limits
  - watchlist caps
  - backpressure and disconnect penalties
  - blocklists and contact-gated presence

---

## 7. CDN-proxied deployment

### 7.1 “Any CDN” baseline
- Use standard HTTP(S), WebSockets, and SSE.
- Avoid vendor-specific dependencies in the core protocol (Cloudflare-specific features must be optional).

### 7.2 Cloudflare notes (for operator docs)
- WebSockets supported on all plans; the upgrade request counts as a single HTTP request.
- WAF/rate limiting apply to the initial 101 upgrade only; not to post-upgrade frames.

Operational requirement: implement heartbeats + reconnect/resume; assume midstream disconnects.

---

## 8. Privacy posture (v1)
- Presence is contacts-only by default.
- Minimize “surveillance API” surfaces:
  - cap watchlists
  - rate-limit watchers
  - coarse last-seen
  - blocklists
  - optional invisibility
- Do not write presence into Polycentric by default.

---

## 9. Risks and mitigations (tracked)
1) MLS correctness in production (state sync, forks, multi-device): mitigated by strongly-consistent DS ordering + CI vectors + “echo-before-apply” commit discipline.
2) KeyPackage lifecycle (one-time use + replenishment): mitigate by pool management + authenticated fetch + rate limiting + optional last-resort.
3) Offline delivery semantics (ordering/dedupe/backpressure): mitigate by per-conversation log + idempotent msg_id + acks.
4) Presence privacy/abuse: mitigate by contacts-only + server enforcement + coarse last-seen + quotas.
5) CDN-proxied reliability: mitigate by keepalive + resume tokens + deterministic catch-up.

---

## 10. References (external)
- MLS Protocol (RFC 9420): https://datatracker.ietf.org/doc/html/rfc9420
- MLS Architecture (RFC 9750): https://datatracker.ietf.org/doc/rfc9750/
- Cloudflare WebSockets docs (WAF inspection note): https://developers.cloudflare.com/network/websockets/
- Polycentric API docs (CDN-friendly query model): https://docs.polycentric.io/protocol/api/
- HTTP Cache-Control (no-store): https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cache-Control
