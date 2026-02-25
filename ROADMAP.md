# Roadmap

This roadmap is structured to retire the highest-risk areas early: MLS correctness, delivery semantics, presence privacy, and CDN-proxied realtime reliability.

## Editing rules (for Codex / no-touch iteration)
- Keep milestone names stable; append new milestones rather than renaming.
- Every milestone MUST include: deliverables, exit criteria, risk retired.
- If scope changes, update the “MVP scope” section first, then ripple changes downward.
- Before implementing MLS/presence beyond scaffolding, add/update ADRs in [DECISIONS.md](DECISIONS.md) and risks in [RISK_REGISTER.md](RISK_REGISTER.md).

---

## 0. MVP scope

### MVP-1 (CLI/TUI-first)
- Auth via Polycentric identity/device
- DM chat (MLS group of size 2)
- CLI + TUI deliverable for primary client experience
- Offline delivery (close client, reopen, catch up)
- Presence: online/offline + coarse last-seen for contacts-only watchlist
- Operator: single-node gateway behind CDN
- Protocol: v1 runs without federation but reserves home-gateway routing metadata to keep v2 cheap

### MVP-2
- Invite-only rooms (MLS groups)
- Basic room governance: owner/admin remove members
- Abuse controls: rate limits, watchlist caps, blocklists

### MVP-3
- Frameworkless web protocol/interop harness (browser MLS via WASM, static assets, no Node/npm required) for gateway+MLS validation.
- Interop: CLI + web harness in the same DM/room.
- Deferred product goal: Polycentric social+chat browser UI integration lands after harness parity.

---

### MVP ↔ phases mapping
- MVP-1 spans Phase 0, Phase 0.5, Phase 1 (gateway skeleton + resume + SSE fallback), Phase 1.5 reservations, and Phase 3.5 Polycentric social.
- MVP-2 adds Phase 4 (rooms v1).
- MVP-3 corresponds to Phase 5a (web harness + interop), with social UI integration deferred to Phase 5b.

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

### Phase 0.5 — CLI/TUI foundation (retire: primary client UX ambiguity)
**Deliverables**
- CLI + TUI client shells capable of Phase 0 MLS flows (create group(2), encrypt/decrypt, persist/reload MLS state).
- Basic UX coherence: shared command vocabulary + TUI navigation for DM conversations and history.
- CLI/TUI integration with Polycentric identity/device provisioning used by MVP-1.

**Exit criteria**
- CLI and TUI both complete the Phase 0 MLS simulation workflow end-to-end on two devices.
- Minimal accessibility checks (keyboard-only navigation) pass in the TUI DM flow.

**Implementation reality (current repo)**
- CLI exists today under `clients/cli/` and is used for the current integration + protocol tests.
- TUI production shell is not implemented yet; roadmap scaffolding is tracked for Phase 5.2 completion gating.
- Current UX validation is CLI-first while TUI scope is being formalized in `clients/docs/production_clients_exit_criteria.md`.

**Risk retired**
- CLI/TUI are first-class and unblock MVP-1 without waiting on web client milestones.

---

### Phase 1 — Gateway skeleton + resume (retire: CDN reliability + core protocol)
**Deliverables**
- Gateway WS server with:
  - session auth (`session.start` with `auth_token`, `device_id`, `device_credential`)
  - resume flow via `resume_token`
  - heartbeats
  - resume + replay (`from_seq`)
- SSE fallback endpoints (`/v1/sse`, `/v1/inbox`) that mirror WS semantics for CDN-disconnect scenarios.
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

### Phase 1.5 — Federation-ready v1 protocol reservations (retire: protocol ossification / costly v2 risk)
**Deliverables**
- Gateway identity surfaced as `gateway_id` with default `gw_local`.
- `conv_home` semantics recorded per conversation; routing metadata emitted on WS/SSE/HTTP inbox responses.
- KeyPackage responses include `served_by` and `user_home_gateway` to stay proxy-compatible.
- ADR 0006 accepted describing the relay-to-home federation posture.
- Spec reserves discovery hints for mapping `gateway_id`/`conv_home` to a reachable destination to keep federation rollout additive.

**Exit criteria**
- Backwards compatibility preserved for v1 clients while tests assert routing metadata is present.
- Deterministic checks green (lint/test/check) with metadata fields covered by automation.

**Risk retired**
- Protocol ossification that would make gateway federation a breaking change.

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
- Multi-device test: 2 users × 2 devices, device loss/wipe + resume via `resume_token` and MLS state resync, all decrypt.
- KeyPackage exhaustion test: system degrades gracefully via rate limits; optional "last-resort" issuance is deferred/not implemented in the current repo.

**Implementation reality (current repo)**
- Retention/GC policy is implemented for SQLite mode with operator-tuned knobs (`GATEWAY_RETENTION_MAX_EVENTS_PER_CONV`, `GATEWAY_RETENTION_MAX_AGE_S`, sweeper interval, SAFE/HARD enforcement).
- Replay remains bounded: requests older than retained history can fail with `replay_window_exceeded` (WS error / SSE HTTP 410).
- Idempotency (`conv_id`, `msg_id`) is enforced for retained rows; pruning old rows intentionally bounds dedupe history.
- See `gateway/docs/retention_and_idempotency.md` for operational guidance and retention drill expectations.

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

**Signoff artifact**
- Presence privacy review mapping + test anchors: `gateway/docs/presence_privacy_review.md`.

**Risk retired**
- Presence is safe enough to ship.

---

### Phase 3.5 — Polycentric social layer MVP (retire: social substrate ambiguity)
**Deliverables**
- Signed Polycentric social events (posts/profile updates) emitted by gateway and verifiable via CDN-friendly HTTP query surfaces.
- HTTP query APIs for social graph and feed retrieval designed for caching/CDN proxies.
- Minimal CLI/TUI UX integration to view/publish social events alongside DM context.

**Exit criteria**
- Social events retrievable via HTTP queries with signature verification and replay protection exercised in automation.
- CLI/TUI users can publish and fetch social events without bypassing caching posture.

**Implementation reality (current repo)**
- Social integration is currently implemented as per-user signed event-log publishing and retrieval surfaces.
- Feed/profile UX is intentionally minimal and primarily exposed through CLI + web harness tooling, not a fully productized browser or TUI experience.
- Phase 5.2 formalizes production UX gates for account/profile/DM/rooms/timeline parity before calling clients production-ready.

**Risk retired**
- “Polycentric-based social platform” claim is grounded with signed events and client UX parity for MVP-1.

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
- CI validates scaled-down/lite profiles in `gateway/tests/test_room_fanout_load_lite.py` and `gateway/tests/test_mls_dm_over_ds.py` (scaled profile).
- Operator-run soak profile is available (not CI-gated) via `scripts/phase4_room_soak.sh`.
- Join/leave churn test with offline users.

**Risk retired**
- Room-scale fanout and MLS commit ordering are validated.

---

### Phase 5 — Web integration (retire: browser crypto + UX parity)
#### Phase 5a — Web protocol/interop harness
**Deliverables**
- Web MLS binding (WASM) and storage (secure key management story).
- Frameworkless/static web protocol harness for gateway WS flows, rooms API helpers, DM MLS demo, vectors UI, and IndexedDB proof-of-concept storage.
- Web MLS binding remains via the Go-to-WASM harness (ADR 0005). UI stack stays minimal even as interop expands.
- Web posture remains frameworkless/static with no Node/npm in the critical path (ADR 0007).
- Interop test suite: web + CLI in same conversations.

**Exit criteria**
- Web harness and CLI can co-exist in the same DM/room with no decryption failures.
- “Device bootstrap” threat model documented and reviewed (see `clients/web/THREAT_MODEL.md`).

**Risk retired**
- Browser MLS and cross-client interop is real.

**Current web UI inventory (repo snapshot)**
- `clients/web/index.html` — static harness shell with gateway/session controls and panels for rooms, DM, and vectors.
- `clients/web/gateway_ws_client.js` — session lifecycle, `conv.subscribe`/`conv.ack`/`conv.send`, and Rooms v1 panel helpers.
- `clients/web/dm_ui.js` — local MLS DM demo with commit echo gating and import/export flows.
- `clients/web/social_ui.js` — minimal signed-event viewer scaffold (read-only/debug; not product-grade social UX).
- `clients/web/mls_vectors_loader.js` + `clients/web/vectors_ui.js` — WASM vector loader and vectors test UI wiring.

#### Phase 5b — Web social+chat UI integration (deferred)
**Deliverables**
- Integrate chat surfaces with Polycentric social feed/profile browser UI.
- Product-grade browser UX beyond protocol harness scope (navigation, social views, and chat/social cohesion).

**Exit criteria**
- Deferred to a later iteration (Phase 6 planning gate) and not required for current Phase 5a completion.

### Phase 5.1 — Web UI posture hardening (retire: dependency/supply-chain creep)
**Deliverables**
- Dependency minimization policy for the web client (frameworkless/static, no Node/npm in critical path; see ADR 0007).
- CSP baseline documented for WS/SSE with wasm-friendly extensions only as required.
- Offline-friendly development workflow for committed web assets.

**Exit criteria**
- Documentation confirms the “no-npm-required” web dev path and dependency policy.
- CSP guidance published and validated against the static artifacts.

### Phase 5.2 — Production clients (Web UI + TUI) (retire: product-readiness ambiguity)
**Deliverables**
- Production gate applies to both clients:
  - Web UI remains frameworkless/static and must not add Node/npm to the critical path.
  - TUI remains stdlib-first unless a dependency has explicit justification and review.
- Account lifecycle:
  - Sign in/session bootstrap, device resume, sign out/session revoke UX for web + TUI.
  - Deterministic reconnect + replay UX with cursor continuity and user-visible status.
  - Explicit identity UX: create/import identity, identity import/export safe boundary, and device rotate guidance (implementation may follow later milestones).
- Profile:
  - MySpace-like nostalgic profile page layout with banner + avatar, About Me (description), Interests (simple text), Friends list (derived from follow events), and Latest Posts/Bulletins (post kind).
  - View/edit profile fields, publish signed profile updates, and render verification/state errors.
- DMs:
  - Create/open DM, send/receive ciphertext-backed messages, replay catch-up, and commit echo-before-apply behavior.
- Rooms:
  - Create room, invite/remove members, send/receive room messages, and membership-state rendering.
  - Server-backed conversation naming parity: shared room title + per-user label + per-user pin ordering across web/TUI.
  - Server-backed conversation hygiene: per-user mute + archive across web/TUI.
- Timeline:
  - Publish post, fetch timeline entries, render per-user event-log ordering, and open author profile from timeline.
  - follow/unfollow UX and Home feed aggregation from self + friends.

**Exit criteria**
- Happy-path flows (web + TUI) are documented and pass smoke checks for:
  - Account lifecycle
  - Profile
  - DMs
  - Rooms
  - Timeline
- Pruning recovery UX is implemented and verified for both web + TUI:
  - Users receive explicit “history pruned” guidance when replay windows are exceeded.
  - Recovery path (resubscribe from earliest retained seq / refresh local view) is one action away and documented.
- Baseline security checklist is complete for both clients (OWASP ASVS themes):
  - Authentication/session handling
  - Token lifecycle + storage constraints
  - Secure local persistence defaults and secret redaction
  - Input/output handling + transport guarantees
- Baseline accessibility checklist passes for web keyboard operation (WCAG 2.x themes):
  - Keyboard-only operability for all primary actions
  - Focus visibility/order and semantic labeling of controls
  - Status/error messaging announced without pointer-only affordances
- Phase 5a remains a harness milestone; production readiness is gated only when Phase 5.2 criteria are satisfied.

**Risk retired**
- “Production-ready web UI + TUI” claim becomes testable, auditable, and resistant to roadmap drift.

---

### Phase 6 — Aspects (E2EE audience groups) planning gate (retire: encrypted audience-scope ambiguity)
**Deliverables (planning only in this phase)**
- Contract doc for encrypted payload envelope shape used inside signed Polycentric social events.
- Key distribution posture for Aspects captured as MLS-backed planning (RFC 9420), including provisioning and membership updates.
- Rotation posture and non-member UX behavior documented before implementation starts.
- Explicit scope marker that this phase is planning-only and does not implement Aspects runtime behavior.

**Exit criteria**
- `clients/docs/aspects_phase6.md` defines envelope format, key distribution plan, rotation rules, and non-member UX.
- Roadmap + contract tests assert this remains a planning gate and does not claim runtime Aspects implementation.
- Social event posture remains signed event-log entries that may carry opaque/encrypted payload bodies.

**Risk retired**
- Scope drift around E2EE audience-group semantics is bounded before implementation.

---

### Phase 7 — Gateway federation v2 (relay-to-home) (retire: multi-gateway ops / routing risk)
**Deliverables**
- Inter-gateway transport and authentication to forward MLS traffic to `conv_home`.
- Routing to `conv_home` for sends/replay with proxying of KeyPackage operations to the home gateway.
- Discovery mechanism standardized and implemented per the gateway directory convention (v2) so routing metadata maps to reachable URLs.
- Operational docs for multi-gateway deployments without introducing multi-writer semantics.

**Exit criteria**
- Federation interop between gateways with preserved ordering/idempotency and no regressions for single-gateway sites.
- Operators can deploy and observe relay-to-home behavior with documented rollouts/rollbacks.

**Risk retired**
- Multi-gateway operational risk and routing ambiguity.

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
- Federation ossification: reserve routing metadata in v1 (conv_home/origin_gateway, KeyPackage served_by/user_home_gateway) and codify relay-to-home posture (ADR 0006).

---

## 4. References (external)
- MLS Architecture (strongly-consistent DS sequencing + commit echo guidance): https://datatracker.ietf.org/doc/rfc9750/
- MLS Protocol (KeyPackage reuse/last-resort/rate limiting): https://datatracker.ietf.org/doc/html/rfc9420
- Cloudflare WebSockets docs (WAF inspection only on upgrade): https://developers.cloudflare.com/network/websockets/
- Polycentric API docs (CDN-friendly querying): https://docs.polycentric.io/protocol/api/
