# Roadmap

This roadmap is structured to retire the highest-risk areas early: MLS correctness, delivery semantics, presence privacy, and CDN-proxied realtime reliability.

## Editing rules (for Codex / no-touch iteration)
- Keep milestone names stable; append new milestones rather than renaming.
- Every milestone MUST include: deliverables, exit criteria, risk retired.
- If scope changes, update the “MVP scope” section first, then ripple changes downward.

---

## 0. MVP scope

### MVP-1 (CLI-first)
- Auth via Polycentric identity/device
- DM chat (MLS group of size 2)
- Offline delivery (close client, reopen, catch up)
- Presence: online/offline + coarse last-seen for contacts-only watchlist
- Operator: single-node gateway behind CDN

### MVP-2
- Invite-only rooms (MLS groups)
- Basic room governance: owner/admin remove members
- Abuse controls: rate limits, watchlist caps, blocklists

### MVP-3
- Web UI integration (browser MLS via WASM)
- Interop: CLI + Web in same DM/room

---

## 1. Milestones (phases)

### Phase 0 — MLS library + correctness harness (retire: MLS risk)
**Deliverables**
- MLS library selection for native + web (WASM) targets.
- CI harness:
  - runs MLS test vectors / conformance suite
  - fuzz/soak tests for state persistence and replay
- CLI local POC:
  - create group(2)
  - encrypt/decrypt
  - persist MLS state to disk and reload cleanly

**Exit criteria**
- CI green on vectors.
- 2-device simulation can exchange 1k messages with state reloads and no forks/decryption failures.

**Risk retired**
- “MLS in production” basics: state machine correctness, persistence, message processing discipline.

---

### Phase 1 — Gateway skeleton + resume (retire: CDN reliability + core protocol)
**Deliverables**
- Gateway WS server with:
  - session auth (challenge + resume token)
  - heartbeats
  - resume + replay (`from_seq`)
- Durable per-conversation log with server-assigned `seq`.
- Protocol smoke tests:
  - reconnect storms
  - duplicate sends
  - gap detection + replay recovery

**Exit criteria**
- Chaos test: force disconnects and resumes (10k cycles) with no message loss and no user-visible duplication.
- Load test: N concurrent sockets with stable CPU/memory.

**Risk retired**
- CDN-proxied realtime reliability (assume disconnections; deterministic catch-up is correct).

---

### Phase 2 — KeyPackage directory + DM MVP (retire: KeyPackage lifecycle + offline delivery)
**Deliverables**
- KeyPackage directory:
  - upload batch for a device
  - fetch N packages for a target user (one-time issuance)
  - pool monitoring and replenishment (client-side)
- DM flow:
  - initiator fetches recipient KeyPackages
  - creates MLS group + sends Welcome via gateway
  - messages stored/forwarded as ciphertext
- Mailbox semantics:
  - idempotent `msg_id`
  - ack cursors per device
  - retention + GC policy

**Exit criteria**
- Multi-device test: 2 users × 2 devices, add/remove/rejoin, all decrypt.
- KeyPackage exhaustion test: system degrades gracefully (rate limit + optional last-resort).

**Risk retired**
- KeyPackage lifecycle and offline delivery semantics are proven.

---

### Phase 3 — Presence MVP with privacy/abuse controls (retire: presence surveillance risk)
**Deliverables**
- Presence lease protocol:
  - `lease(online, ttl)` renewals
  - `sub(watchlist)` + events
  - invisible mode
- Policy enforcement:
  - contacts-only gating
  - watchlist caps
  - rate limits per watcher and per target
  - blocklists
  - coarse last-seen buckets only

**Exit criteria**
- Scrape simulation: bots attempting large watchlists get throttled/blocked without harming normal users.
- Privacy review signoff: presence does not become a convenient tracking API.

**Risk retired**
- Presence is safe enough to ship.

---

### Phase 4 — Rooms v1 (retire: fanout + commit races)
**Deliverables**
- Invite-only rooms:
  - create room, invite members, remove members
- Fanout:
  - server assigns seq; broadcasts to subscribers
- Commit discipline:
  - clients do not apply their own Commit until echoed
  - tie handling relies on strongly-consistent ordering

**Exit criteria**
- Load test: 1k-member room, 100 msg/s for 1 hour, no MLS divergence.
- Join/leave churn test with offline users.

**Risk retired**
- Room-scale fanout and MLS commit ordering are validated.

---

### Phase 5 — Web integration (retire: browser crypto + UX parity)
**Deliverables**
- Web MLS binding (WASM) and storage (secure key management story).
- Web chat UI integrated with Polycentric social UI.
- Interop test suite: web + CLI in same conversations.

**Exit criteria**
- Web and CLI can co-exist in the same DM/room with no decryption failures.
- “Device bootstrap” threat model documented and reviewed.

**Risk retired**
- Browser MLS and cross-client interop is real.

---

## 2. Cross-cutting deliverables (done continuously)
- Observability:
  - structured logs (no plaintext)
  - metrics: reconnects, replay sizes, acks, presence subs, rate-limit hits
- Operator docs:
  - behind-CDN deployments (Cloudflare examples + generic CDN)
  - backup/restore of gateway DB
  - retention tuning
- Security reviews at Phase 0/2/3/5.

---

## 3. Risk register (tracking)
- MLS forks / state loss: mitigated by DS ordering + echo-before-apply + recovery procedure.
- KeyPackage exhaustion/DoS: rate limits + authenticated fetch + optional last-resort.
- Presence scraping: contacts-only + caps + rate limits + invisible mode.
- CDN disconnects: heartbeats + resume + deterministic replay.
- Abuse/spam/moderation: invite controls + resource quotas; add governance primitives before “public rooms”.

---

## 4. References (external)
- MLS Architecture (strongly-consistent DS sequencing + commit echo guidance): https://datatracker.ietf.org/doc/rfc9750/
- MLS Protocol (KeyPackage reuse/last-resort/rate limiting): https://datatracker.ietf.org/doc/html/rfc9420
- Cloudflare WebSockets docs (WAF inspection only on upgrade): https://developers.cloudflare.com/network/websockets/
- Polycentric API docs (CDN-friendly querying): https://docs.polycentric.io/protocol/api/
