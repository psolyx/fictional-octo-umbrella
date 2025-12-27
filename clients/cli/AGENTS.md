# AGENTS.md (clients/cli/)

This file applies to changes under clients/cli/.

## CLI/TUI priorities
- Deterministic sync:
  - never "guess" state; rely on `seq` + replay
  - on gaps, resubscribe and recover before rendering "committed" state
- Safe persistence:
  - persist MLS state atomically (write temp + fsync + rename)
  - persist `ack_seq` and `resume` token safely
- UX baseline:
  - fast startup even with large history (load cursors first; fetch on demand)
  - robust offline behavior (queue outbound; retry idempotently)

## Security requirements
- Never print plaintext to debug logs.
- Never print keys, MLS state blobs, or resume tokens.
- If you add crash reports, scrub everything by default.

## Chat semantics (v1)
- Delivery is at-least-once; dedupe by `(conv_id, msg_id)`.
- Treat "delivered" as: message echoed back by server with a `seq`.
- Maintain an LRU dedupe cache per conversation.

## Presence semantics (v1)
- Display only:
  - online/offline
  - coarse last-seen buckets
- Do not implement typing indicators unless explicitly requested.

## Required tests (minimum bar)
- message send retry after forced disconnect (same msg_id) does not duplicate in UI
- replay catch-up from `ack_seq`
- MLS state persistence and reload works across restarts

## Docs
If CLI behavior implies a protocol expectation, reflect it:
- Update GATEWAY_SPEC.md if you are depending on a new guarantee.
