# Gateway federation posture: relay-to-home

## Status
Accepted

## Context
Today v1 deployments run a single gateway behind a CDN. Protocol frames and implementation implicitly assume the ordering server is the connected gateway, which would make later federation expensive or force a dual-stack. We need an explicit posture for v2 so we can reserve routing metadata now while keeping v1 non-federated.

## Decision
- Federation, when added, will use **relay-to-home** semantics: each conversation has a single ordering authority (`conv_home`) that assigns `seq`.
- Edge gateways MAY accept traffic but must forward to the conversation's home gateway; multi-writer federation is out of scope.
- Protocol reserves routing metadata (`conv_home`, `origin_gateway`, optional `destination_gateway`) and KeyPackage fields (`served_by`, `user_home_gateway`) in v1 to keep v2 changes additive.
- Identifiers are stable: `gateway_id` **MUST** be globally unique in federated deployments and remain stable over time, and `conv_home` **MUST** be assigned on conversation creation and **MUST NOT** change. Clients **MUST NOT** assume `origin_gateway == conv_home`, though in the current single-gateway v1 posture they will typically be equal.

### Discovery (reserved)
- Discovery of `gateway_id`/`conv_home` to a reachable URL or transport destination is reserved in the specification for v1 but intentionally not implemented; later federation work will define and standardize the mapping.

## Consequences
- v1 stays single-gateway but emits routing metadata so clients remain compatible as federation arrives.
- Future work focuses on inter-gateway auth/transport and routing to `conv_home`, not multi-writer reconciliation.
- Operators can plan deployments knowing ordering remains centralized per conversation; scaling is via relay rather than shared writes.
- Gateway discovery is reserved for the spec but not implemented in v1; later federation work must define how `gateway_id` (including `conv_home`) maps to a reachable URL or transport destination.
