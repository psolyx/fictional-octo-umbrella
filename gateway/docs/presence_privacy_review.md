# Presence Privacy Review (Phase 3 signoff)

## Scope and threat model

This signoff covers gateway presence behavior in the Phase 3 MVP scope with emphasis on:

- **scraping**: bulk watchlist probes to enumerate online status.
- **stalking**: repeated polling of a single target's status transitions.
- **"last seen" leakage**: deriving precise activity timelines from presence metadata.

The objective is to keep presence useful for contacts while preventing it from becoming a convenient tracking API.

## Implemented mitigations

### contacts-only visibility

Presence subscriptions are gated to authorized relationships (contacts-only by default) so arbitrary accounts cannot query random targets.

### watchlist cap

Watch requests enforce bounded watchlists so a single watcher cannot subscribe to unbounded target sets.

### rate limit controls

Presence updates and watch operations are subject to per-watcher and per-target rate limit controls to blunt scrape/stalk patterns.

### invisible mode

Clients can request **invisible** behavior to suppress online exposure while preserving private session behavior.

### coarse last-seen buckets

Presence exposes coarse buckets rather than exact timestamps to reduce precision of behavioral inference.

## Evidence mapping to tests

- `gateway/tests/test_presence.py`
  - baseline presence policy checks, authorization, and state semantics.
- `gateway/tests/test_presence_scrape_simulation.py`
  - scrape simulation validating throttle/block behavior under abusive watch patterns.

Together these tests provide automated guardrails for the controls listed above.

## Residual risk and operator notes

- Presence metadata is still sensitive even with controls; operators should monitor abuse signals and keep gateway/runtime limits enabled.
- This review is a lightweight Phase 3 signoff artifact and should be revised when presence policy semantics change.
