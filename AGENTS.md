# AGENTS.md

## Source of truth
- Read these docs first for any task:
  - ARCHITECTURE.md
  - ROADMAP.md
  - GATEWAY_SPEC.md
- If implementation and spec disagree: update implementation to match spec.
- If spec is wrong/ambiguous: propose a spec change first (edit GATEWAY_SPEC.md), then implement.

## Workflow rules
- Work in small PR-sized chunks. One logical change per PR.
- Do not change API message names (`t`) once published; deprecate instead.
- Never log plaintext message content. Ciphertext only.
- Prefer additive changes; avoid large refactors unless requested.

## Verification (MUST run)
- `make test` (or `npm test` / `cargo test` once added)
- `make lint` (or `npm run lint`)
- If no tests exist yet: add at least one new test that fails before and passes after.

## Deliverables
- Update docs when behavior changes:
  - ARCHITECTURE.md for architectural changes
  - GATEWAY_SPEC.md for protocol/semantics changes
  - ROADMAP.md for milestone changes

## Security / privacy constraints
- Presence is soft-state only; do not persist to Polycentric by default.
- Presence visibility is contacts-only by default; enforce caps and rate limits.
- KeyPackages are one-time use; implement pool replenishment and rate limits.
