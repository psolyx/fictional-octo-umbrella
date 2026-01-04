# AGENTS.md (gateway/)

This file applies to changes under gateway/.

## Absolute invariants
- Do not break the ordering invariant:
  - Server assigns monotonically increasing `seq` per `conv_id`.
  - Server broadcasts messages in `seq` order.
- Do not break idempotency:
  - `(conv_id, msg_id)` is an idempotency key.
  - Retried sends must map to the same `seq` or be a no-op.
- Do not break "echo-before-apply" commit discipline:
  - Clients rely on server echo to apply handshake changes deterministically.

If you need to change any of the above:
- Update GATEWAY_SPEC.md first and add a migration plan.

## Security + privacy requirements
- Never log plaintext. Do not store plaintext anywhere.
- Logs must not include:
  - decrypted content
  - raw MLS state blobs
  - presence watchlists (store counts only if needed)
- Presence must not become a tracking API:
  - enforce contacts-only visibility by default
  - hard caps on watchlist size
  - rate limit per watcher and per target
  - blocklist support
  - coarse last-seen buckets only

## Rate limiting and abuse
- CDN WAF does not protect post-upgrade WS frames. App-layer quotas are mandatory.
- Implement:
  - per-device message quotas
  - max frame size
  - backpressure handling (disconnect/429 equivalents)
  - resource caps for subscriptions, watchlists, replay windows

## Durability and correctness
- Conversation log writes must be durable before acking acceptance.
- Replay is inclusive from `from_seq`.
- Gap handling must be deterministic; no "best effort" silent skipping.

## Required tests (minimum bar)
Any change that affects protocol or ordering MUST add/extend tests:
- idempotent send retry
- replay from cursor
- reconnect/resume storm
- ordering correctness under concurrent sends
- presence caps + authorization enforcement

If no harness exists yet, create:
- an integration test that spins gateway + a fake client and asserts `seq`/replay behavior.

## Performance expectations (v1)
- Avoid O(N) per message per subscriber when possible.
- Keep per-connection memory bounded.
- Any unbounded structure must have a cap and eviction strategy.

## Docs
If you change any wire behavior:
- Update GATEWAY_SPEC.md (normative)
- Update ARCHITECTURE.md if responsibilities move

## Load test runbook (Phase 1)
- Prep: `ALLOW_AIOHTTP_STUB=0 make -C gateway setup` to ensure `gateway/.venv` exists, then from repo root run the tool.
- Baseline (server spawned automatically): `python tools/gateway_loadtest_v2.py --spawn-server --sessions 200 --duration-seconds 60 --messages 0 --drain-seconds 5`.
- Resume storm check: add `--resume-cycles 3` to the baseline command to verify reconnect resilience.
- Message load: approximate 1 msg/sec per socket with `--messages 60 --message-interval 1 --duration-seconds 60` (adjust sessions as needed) and combine with `--resume-cycles` if desired.
- Record for each run: max RSS, average/peak CPU%, total events, reconnect count, and confirm duplicate msg_ids reported as `0`.
- Optional: `--json-out report.json` captures a machine-readable summary for sharing.
