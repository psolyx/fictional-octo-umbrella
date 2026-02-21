# TUI client scaffold (Phase 5.2)

This directory reserves the production TUI client scope defined by **Phase 5.2 — Production clients (Web UI + TUI)**.

## Current status
- Not implemented yet.
- Exists so roadmap and tests can track production-gate requirements without implying completion.

## Constraints
- Prefer stdlib-first implementation.
- Avoid heavy dependencies in the critical path unless justified with clear tradeoff notes.
- Keep deterministic replay/resume semantics aligned with gateway protocol contracts.

## Planned code sharing with `clients/cli/src`
- Reuse protocol/session/storage primitives from `clients/cli/src/cli_app` where practical.
- Keep UI rendering concerns isolated from transport/state primitives.
- Favor additive shared modules over cross-importing UI glue.

## Local placeholder run
```bash
PYTHONPATH=clients/tui/src python -m tui_app
```


## Planned initial milestones (documentation-only)
- M1: startup shell + account lifecycle command map.
- M2: DM/room transcript panes with replay cursor visibility.
- M3: timeline/profile panes with signed-event status indicators.
