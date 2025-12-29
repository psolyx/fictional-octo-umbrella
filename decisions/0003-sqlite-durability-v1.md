# SQLite durability for the gateway

## Status
Accepted

## Context
The gateway currently keeps conversation events, cursors, and sessions in memory. That design loses sequencing, idempotency, and session resume data on restart, breaking replay and ordered delivery guarantees called out in the gateway spec (§7). We need a durable backend that survives process restarts without adding external dependencies or compromising ordering.

## Decision
- Use SQLite (stdlib `sqlite3`) as the first durable backend for the gateway runtime.
- Enable WAL mode, `synchronous=NORMAL`, `foreign_keys=ON`, and `busy_timeout=5000` on open to balance durability and concurrency.
- Store durable tables for conversation events (`conv_events`), per-conversation sequence state (`conv_seq`), per-device cursors (`cursors`), and resumable sessions (`sessions`). Enforce uniqueness on (`conv_id`, `msg_id`) for idempotency and monotonic `seq` assignment per `conv_id` via the `conv_seq` table.
- Allocate sequences atomically with `BEGIN IMMEDIATE`, inserting default sequence rows, reading `next_seq`, incrementing, and committing in order. Idempotent retries return the existing event without broadcasting duplicates.
- Persist cursor acknowledgements and session resume tokens so reconnecting clients inherit the correct `next_seq` and can resume websockets across restarts.

## Consequences
- Gateway deployments can run in persistent mode by passing a SQLite path; in-memory mode remains available when no path is provided.
- Ordered delivery and idempotent retry guarantees now survive process restarts, enabling deterministic replay and resumable sessions across disconnects.
- Future migrations must bump the schema version; additional storage engines can follow the same interfaces to drop in at runtime.
