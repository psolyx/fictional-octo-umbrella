# AGENTS.md (repo root)

This file is read by Codex and applies to the whole repo unless overridden by a closer AGENTS.md.

## Source of truth
Read these docs first for any task:
- ARCHITECTURE.md
- ROADMAP.md
- GATEWAY_SPEC.md

If implementation and spec disagree:
1) Prefer updating implementation to match spec.
2) If spec is wrong/ambiguous, propose a spec change first (edit GATEWAY_SPEC.md), then implement.

## Repo intent (high level)
- Polycentric provides identity + social/event-log substrate (cache/CDN-friendly).
- Realtime gateway provides chat + presence (uncacheable, CDN-proxied).
- Chat is E2EE via MLS everywhere (rooms + DMs; DM = 2-member MLS group).
- Gateway stores/forwards ciphertext only; never plaintext.

## Workflow rules
- Small PR-sized changes. One logical change per PR.
- Keep API stable:
  - Do not rename protocol message names (`t`).
  - Deprecate instead of breaking changes.
- Prefer additive changes. Avoid refactors unless requested.
- Security posture:
  - Never log plaintext.
  - Do not add telemetry that can reconstruct social graph or presence scraping.
- Docs must be updated when behavior/semantics change:
  - ARCHITECTURE.md for architecture changes
  - GATEWAY_SPEC.md for protocol/semantics changes
  - ROADMAP.md for milestone/scope changes

## Required verification
You MUST run before finalizing a change (pick what exists; add missing targets as repo matures):
- `make fmt`
- `make lint`
- `make test`
- `make check` (preferred if available)

If the repo has no tests yet, add at least one:
- A unit/integration test that fails before and passes after.

## Output expectations for PRs
- Include:
  - What changed
  - Why (reference spec section / roadmap milestone)
  - How to verify (exact commands)
- Avoid noisy formatting-only diffs unless the change is explicitly formatting.

## Defaults / constraints (v1)
- Presence:
  - soft-state leases only (TTL), contacts-only by default
  - watchlist caps + per-watcher and per-target rate limits
  - coarse last-seen buckets only
- KeyPackages:
  - one-time use issuance, pool replenishment
  - rate limit fetches; authenticated by default
- CDN reality:
  - assume disconnects and implement resume/replay deterministically
  - app-layer rate limits are mandatory on WS

## Directory overrides
- gateway/AGENTS.md overrides gateway-specific rules
- clients/cli/AGENTS.md overrides CLI-specific rules
