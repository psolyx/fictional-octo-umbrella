# Gateway sequencing, idempotency, and echo-before-apply

## Status
Proposed

## Context
Gateway connections ride through CDN proxies and are expected to drop midstream. MLS commits are safety-critical; applying them out of order or twice can fork group state. Clients also retry `conv.send` on transient failures, so the Delivery Service needs idempotency and deterministic ordering to survive disconnects and retries.

## Decision
- Assign a monotonically increasing `seq` per `conv_id` on the server. Every enqueued message receives the next `seq` in order; DS broadcasts deliveries in `seq` order.
- Require (`conv_id`, `msg_id`) as the idempotency key. Retries with the same pair return the same `seq` and MUST NOT create duplicates.
- Enforce “echo-before-apply” for MLS Commits: clients MUST wait for their own commit to be echoed back with its assigned `seq` before advancing state. The DS echoes every message—including the sender’s—to preserve ordering across devices.

## Consequences
- Clients need tests that cover retrying the same `msg_id` and confirm the returned `seq` stays stable.
- Delivery Service implementations must persist per-conversation counters and idempotency maps durable enough to survive reconnects and failovers.
- Client UX must tolerate delays between send and echo; optimistic UI cannot assume local apply succeeded until the echo arrives.
- When DS storage fails, messages MAY be rejected; clients MUST surface retry guidance without duplicating state.
