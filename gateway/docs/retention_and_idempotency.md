# Retention and Idempotency (Phase 2 implementation reality)

## Retention policy knobs (SQLite durability mode)

Conversation retention/GC is configurable via environment variables when `db_path` (SQLite mode) is enabled:

- `GATEWAY_RETENTION_MAX_EVENTS_PER_CONV` (default `0`): keep the newest N events per conversation. `0` disables this cap.
- `GATEWAY_RETENTION_MAX_AGE_S` (default `0`): prune events older than this age in seconds. `0` disables age-based pruning.
- `GATEWAY_RETENTION_SWEEP_INTERVAL_S` (default `60`): periodic sweep cadence when retention is enabled.
- `GATEWAY_CURSOR_STALE_AFTER_S` (default `0`): cursor freshness window. `0` means all cursors are treated as active.
- `GATEWAY_RETENTION_HARD_LIMITS` (default `0`):
  - `0` = SAFE mode (prefer preserving unacked history for active devices)
  - `1` = HARD mode (strictly enforce caps even if stale/offline devices lose replayability)

If both max-events and max-age are disabled (`0` + `0`), retention remains effectively unbounded (default behavior).

## SAFE vs HARD retention behavior

The gateway tracks `next_seq` cursor progress per `(device_id, conv_id)` and updates cursor freshness on every `conv.ack`.

- **SAFE mode** (`GATEWAY_RETENTION_HARD_LIMITS=0`):
  - pruning avoids deleting events with `seq >= (active_min_next_seq - 1)`
  - in practice, retained history is bounded by policy but never prunes beyond what all *active* devices have acknowledged.
- **HARD mode** (`GATEWAY_RETENTION_HARD_LIMITS=1`):
  - retention caps are enforced regardless of cursor state
  - offline or stale devices may request history that has already been pruned.

Cursor freshness uses `GATEWAY_CURSOR_STALE_AFTER_S`:

- when set to `0`, every cursor counts as active
- when set to `>0`, only cursors updated within that window constrain SAFE pruning.

## Replay window exceeded behavior

Replay is bounded by retained history. When a client asks for `from_seq` older than retained history:

- WS `conv.subscribe` returns an `error` frame with `code = "replay_window_exceeded"`.
- SSE `GET /v1/sse` returns HTTP `410` with JSON:

```json
{
  "code": "replay_window_exceeded",
  "message": "requested history has been pruned",
  "earliest_seq": 42,
  "latest_seq": 84
}
```

This only applies when retention is enabled. With retention disabled, behavior is unchanged.

## Idempotency window semantics

The idempotency key is `(conv_id, msg_id)`.

- Retries are deduplicated while the corresponding retained rows still exist.
- If retention removes old data, retries for pruned entries may no longer map to the original `seq` and can be treated as new sends.

In short: idempotency guarantees are strongest for the retained window and depend on retention policy.

## KeyPackage “last-resort” issuance

Roadmap language may mention optional last-resort behavior for KeyPackage exhaustion.

- In the current repo, optional "last-resort" issuance is **deferred / not implemented**.
- Current graceful-degradation posture is to use existing limits/validation and surface exhaustion conditions clearly.

## PoC operator posture

For PoC deployments:

- start with retention disabled unless requirements demand bounded storage,
- enable conservative SAFE caps first and monitor cursor lag,
- run periodic retention drills (short windows in a test environment) to validate replay-window handling and operational runbooks.
