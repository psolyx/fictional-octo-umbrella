# Record architecture decisions with ADRs

## Status
Accepted

## Context
This project spans multiple components (gateway, clients, social layer) with long-lived invariants (MLS ordering, presence privacy, CDN reality). Decisions that alter these invariants or add new guarantees need durable, discoverable documentation.

## Decision
Adopt Architecture Decision Records (ADRs) in this repository. Each significant architecture or product decision will be recorded as an ADR following the template in `DECISIONS.md` and stored under `decisions/NNNN-slug.md`.

## Consequences
- Future architectural changes require an ADR and review before implementation.
- Contributors gain a consistent place to find the rationale behind constraints and trade-offs.
- Superseded decisions remain traceable through ADR history.
