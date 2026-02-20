# Retention and Idempotency (Phase 2 implementation reality)

## Current behavior in this repo

- The PoC gateway stores conversation log and idempotency data durably.
- There is **no automatic TTL/GC policy** implemented in the current codepath.
- Retention is effectively unbounded until an operator rotates or prunes the backing database.

## Idempotency window semantics

The idempotency key is `(conv_id, msg_id)`.

- Retries are deduplicated while the corresponding retained rows still exist.
- If operators delete old data, retries for those deleted entries may no longer map to the original `seq` and can be treated as new sends.

In short: idempotency guarantees are strongest for the retained window and depend on retention policy.

## KeyPackage “last-resort” issuance

Roadmap language may mention optional last-resort behavior for KeyPackage exhaustion.

- In the current repo, optional "last-resort" issuance is **deferred / not implemented**.
- Current graceful-degradation posture is to use existing limits/validation and surface exhaustion conditions clearly.

## PoC operator posture

For PoC deployments:

- plan explicit DB rotation/pruning windows,
- retain backups/snapshots before destructive maintenance,
- perform maintenance with awareness that old-message idempotent retries may lose dedupe after deletion.
