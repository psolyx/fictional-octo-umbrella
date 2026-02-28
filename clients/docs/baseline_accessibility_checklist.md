A11Y_CHECKLIST_V1

# Baseline accessibility checklist (Phase 5.2)

This checklist captures existing, auditable keyboard and live-region accessibility baselines for web + TUI surfaces.

## Keyboard-only operability (primary surfaces)
- [x] Account actions are reachable/operable using keyboard controls.
- [x] Profile actions and form edits are keyboard-operable.
- [x] DMs send/subscribe/ack flows are keyboard-operable.
- [x] Rooms controls are keyboard-operable.
- [x] Timeline/profile feed controls are keyboard-operable.
- [x] TUI keybindings include discoverable help overlay text for conversation filters/search.

## Focus visible posture
- [x] Web stylesheet defines `:focus-visible` outlines for buttons/inputs/textareas and key list controls.

## Status/error announcements
- [x] Session expired banner exposes `role="status"` with `aria-live="polite"`.
- [x] Replay-window (history pruned) banner exposes `role="status"` with `aria-live="polite"`.
- [x] Conversation filter status line exposes `role="status"` with `aria-live="polite"`.

## Roving tabindex for arrow-key list navigation
- [x] Conversations list uses roving-tabindex markers and `tabindex` updates (`0` for selected, `-1` otherwise) to support arrow-key navigation.

## Audit command
- [x] `env PYTHONPATH=clients/cli/src python -m cli_app.phase5_2_static_audit_main`
  - This verifies focus-visible, live-region, roving-tabindex, and TUI help-overlay markers deterministically.
