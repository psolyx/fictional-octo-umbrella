# Production clients exit criteria (Phase 5.2)

This document is codex-facing guidance for implementing and verifying **Phase 5.2 — Production clients (Web UI + TUI)** in `ROADMAP.md`.

## Scope and intent
- Define a production gate for both frameworkless web UI and stdlib-first TUI.
- Provide explicit, testable user-flow contracts for:
  - Account lifecycle
  - Profile
  - DMs
  - Rooms
  - Timeline
- Keep requirements additive to existing harness milestones (Phase 5a stays an interop harness).

## Definition of Done — Web UI
- Frameworkless/static delivery is preserved (no Node/npm in critical path).
- All happy-path flows complete with deterministic reconnect/replay behavior.
- Pruning recovery UX is available from the primary chat/timeline surfaces.
- Security checklist items are verified for browser storage/session handling.
- Accessibility checklist items pass for keyboard-only operation and focus management.
- Smoke tests (manual + automated placeholders) are executed and recorded.

### Web UI DoD checklist by capability

#### Account lifecycle (Web UI)
- [ ] Session start flow succeeds from clean browser state.
- [ ] Session resume flow succeeds after controlled reconnect.
- [ ] Session-expired state is rendered with re-auth action.
- [ ] Sign-out clears in-memory auth/session state immediately.
- [ ] Sign-out clears persisted token material for the web origin.

#### Profile (Web UI)
- [ ] Profile view renders current values and last-update metadata.
- [ ] Profile edit validates required fields before publish.
- [ ] Signed profile publish success/failure states are visible.
- [ ] Publish retry path exists without full page reload.

#### DMs (Web UI)
- [ ] DM open/create path reaches a subscribed conversation state.
- [ ] Send action transitions message from pending to echoed state.
- [ ] Replay from cursor recovers history deterministically.
- [ ] Duplicate inbound events are deduplicated in render path.
- [ ] Pruned replay error offers explicit recovery action.

#### Rooms (Web UI)
- [ ] Room create path reports server-confirmed room identity.
- [ ] Invite/remove actions show permission errors when applicable.
- [ ] Room send/echo loop preserves visible ordered timeline.
- [ ] Membership changes are reflected without manual refresh.
- [ ] Replay after reconnect restores room state and messages.

#### Timeline (Web UI)
- [ ] Timeline fetch from HTTP query endpoints renders deterministic ordering.
- [ ] Publish flow shows optimistic/pending + confirmed states.
- [ ] Author profile navigation is keyboard reachable.
- [ ] Retry controls exist for failed fetch/publish actions.

## Definition of Done — TUI
- TUI app boots from repo with documented invocation path.
- All happy-path flows complete with deterministic reconnect/replay behavior.
- Pruning recovery UX is available from TUI primary navigation.
- Security checklist items are verified for local state/token persistence.
- Core keyboard navigation is documented and validated for required flows.
- Smoke tests (manual + automated placeholders) are executed and recorded.

### TUI DoD checklist by capability

#### Account lifecycle (TUI)
- [ ] Login/bootstrap command succeeds from clean local profile.
- [ ] Resume command/path succeeds across restart/reconnect.
- [ ] Session-expired state renders with guided recovery text.
- [ ] Sign-out command clears runtime + persisted session material.

#### Profile (TUI)
- [ ] Profile screen shows current values and status metadata.
- [ ] Edit workflow validates input and confirms publish result.
- [ ] Error states are visible in status line and command output.

#### DMs (TUI)
- [ ] DM open/create command enters subscribed state.
- [ ] Send workflow marks pending until echoed `seq` observed.
- [ ] Replay from cursor resumes deterministically.
- [ ] Duplicate events are not rendered twice in transcript view.
- [ ] Pruned replay state offers one-key recovery action.

#### Rooms (TUI)
- [ ] Room create/open paths resolve to stable room context.
- [ ] Invite/remove workflows report authorization failures cleanly.
- [ ] Send/echo loop maintains ordered transcript.
- [ ] Membership changes render in room state panel/log.

#### Timeline (TUI)
- [ ] Timeline command fetches and renders signed events.
- [ ] Publish command confirms success/failure with retry guidance.
- [ ] Author-profile jump command works from timeline items.

## User-flow contracts

### Account lifecycle
1. User starts client and chooses sign-in/device bootstrap.
2. Client obtains session credentials and establishes gateway session.
3. Client shows authenticated state, user id, and connection status.
4. User can sign out, clearing active session material from runtime + storage.
5. User can restart and resume session using supported resume/session UX.

### Profile
1. User opens Profile surface.
2. User views current profile values and signature/verification status.
3. User edits profile fields and submits signed update.
4. Client confirms publish success and updates rendered state.
5. On failure, client presents actionable retry/error messaging.

### DMs
1. User opens DM list and selects/creates a direct conversation.
2. Client subscribes using persisted/default replay cursor.
3. User sends a message; client tracks pending state until echoed with `seq`.
4. Client receives/decrypts echoed + remote events and renders ordered timeline.
5. On reconnect, client replays from stored cursor and deduplicates deterministically.

### Rooms
1. User creates room or opens existing room.
2. User invites/removes members (authorized role only).
3. User sends room messages and sees echoed ordering with `seq`.
4. Client renders membership and permission-state changes.
5. On reconnect, room state and messages recover from replay/cursor state.

### Timeline
1. User opens timeline/feed surface.
2. User fetches signed events from CDN-friendly HTTP query endpoints.
3. User publishes a new post/event and sees it appear with ordering metadata.
4. User opens author profile from timeline entry.
5. Client handles stale/missing data with explicit refresh/retry controls.

## User-flow acceptance contracts

### Account lifecycle acceptance contract
- Preconditions:
  - Client has valid network path to gateway.
  - User has valid identity/device bootstrap material.
- Expected outcomes:
  - Session enters ready/authenticated state.
  - Resume path works until token/session expiry window closes.
  - Sign-out removes session state from active runtime + durable storage.
- Error contracts:
  - Auth failure exposes deterministic error category and retry path.
  - Resume failure degrades to explicit fresh-login requirement.

### Profile acceptance contract
- Preconditions:
  - Authenticated session exists.
- Expected outcomes:
  - Profile load succeeds from canonical signed event source.
  - Signed profile publish updates local rendered state on confirmation.
- Error contracts:
  - Validation failure identifies invalid fields.
  - Publish failure preserves unsent edits for retry.

### DMs acceptance contract
- Preconditions:
  - Authenticated session exists.
  - Peer identity is resolvable for DM bootstrap or prior DM exists.
- Expected outcomes:
  - DM send receives echoed event with server-assigned `seq`.
  - Replay from stored cursor recovers unseen events in order.
  - Duplicate server deliveries are deduplicated by `(conv_id, msg_id)` semantics.
- Error contracts:
  - Replay window exceeded is surfaced as explicit pruned-history state.
  - Recovery action is available without reconfiguring account/session.

### Rooms acceptance contract
- Preconditions:
  - Authenticated session exists.
  - User has create/open authorization for target room operation.
- Expected outcomes:
  - Room operations (create/invite/remove/send) complete with visible confirmations.
  - Conversation state remains coherent across reconnect/replay.
- Error contracts:
  - Unauthorized moderation actions return explicit access errors.
  - Invite/remove failures expose actionable retry text.

### Timeline acceptance contract
- Preconditions:
  - Authenticated session for publish operations.
  - HTTP query endpoints reachable for fetch operations.
- Expected outcomes:
  - Fetch produces ordered signed events.
  - Publish appends to per-user event-log and appears in subsequent fetch.
  - Author profile navigation is available from timeline entry.
- Error contracts:
  - Fetch/publish failures provide retry affordance and non-destructive recovery.

## Pruning recovery UX requirements
- Trigger: replay request exceeds retained history window.
- Web UI:
  - Show visible “history pruned” banner with bounded context.
  - Provide one-click recovery action to resubscribe from earliest retained seq.
- TUI:
  - Show explicit pruned-history state in conversation status line/panel.
  - Provide one-key recovery action to continue from earliest retained seq.
- Both clients:
  - Explain that older history is unavailable due to retention policy.
  - Avoid silent data loss; recovery action must be explicit and logged in UX state.

## Security checklist (baseline)
- Auth/session/token handling:
  - Session tokens scoped, rotated, and cleared on sign out.
  - Resume/session secrets never written to logs.
- Safe storage:
  - Persist secrets/state with least exposure and clear file/storage boundaries.
  - Separate user-facing exports from secret-bearing internal state.
- Transport and protocol integrity:
  - TLS-protected transport only; reject insecure downgrade paths.
  - Echo-before-apply behavior is preserved for local commits.
- Input/output safety:
  - Untrusted network payloads are validated before render/persist.
  - Error surfaces avoid leaking secrets or sensitive metadata.
- OWASP ASVS themes reference:
  - V2 (Authentication), V3 (Session Management), V8 (Data Protection), V9 (Communications), V10 (Malicious Input Handling).

## Accessibility checklist (web baseline)
- WCAG 2.x keyboard operation coverage for primary workflows.
- Visible focus indicator and predictable focus order across screens.
- Semantic labels/roles for form controls, buttons, and status regions.
- Non-color-only affordances for status/error/success states.
- Keyboard-only completion for account lifecycle, profile, DMs, rooms, and timeline flows.

## Smoke tests

### Manual smoke tests
- Account lifecycle happy path (sign in, resume, sign out).
- Profile edit + verification status rendering.
- DM send/echo/replay recovery.
- Room create/invite/send/replay recovery.
- Timeline publish/fetch/profile navigation.
- Pruning recovery path (history pruned message + recovery action).

### Automated smoke-test placeholders
- Contract test: required headings/markers remain in roadmap + this spec.
- Contract test: Phase 5a is identified as harness and Phase 5.2 as production gate.
- Placeholder E2E hooks for future web and TUI happy-path automation.

### Suggested automated smoke-test targets (placeholder inventory)
- Account lifecycle:
  - `test_account_lifecycle_web_happy_path`
  - `test_account_lifecycle_tui_happy_path`
  - `test_session_resume_web_after_reconnect`
  - `test_session_resume_tui_after_restart`
- Profile:
  - `test_profile_web_view_edit_publish`
  - `test_profile_tui_view_edit_publish`
- DMs:
  - `test_dm_web_send_echo_replay`
  - `test_dm_tui_send_echo_replay`
  - `test_dm_pruning_recovery_web`
  - `test_dm_pruning_recovery_tui`
- Rooms:
  - `test_room_web_create_invite_send`
  - `test_room_tui_create_invite_send`
  - `test_room_replay_reconnect_web`
  - `test_room_replay_reconnect_tui`
- Timeline:
  - `test_timeline_web_fetch_publish_profile_jump`
  - `test_timeline_tui_fetch_publish_profile_jump`

## Release gate evidence checklist
- [ ] ROADMAP Phase 5.2 section present with deliverables + exit criteria + risk retired.
- [ ] This spec document present and updated for current implementation state.
- [ ] Web UI manual smoke log attached for all required flows.
- [ ] TUI manual smoke log attached for all required flows.
- [ ] Automated contract tests green in local and CI environments.
- [ ] Security checklist reviewed and signed off.
- [ ] Accessibility checklist reviewed and signed off.

## Implementation notes for Codex (guardrails)
- Build only what is required to satisfy defined capability flows.
- Keep production gate semantics explicit and testable.
- Do not collapse Phase 5a harness goals into production-readiness claims.
- Avoid adding dependencies or architecture changes not required by the checklist.
- Prefer incremental slices that each preserve roadmap/spec contract tests.

## Traceability matrix (Phase 5.2)

| Capability | Required in ROADMAP Phase 5.2 | Required in Web UI DoD | Required in TUI DoD | Contract test anchor |
| --- | --- | --- | --- | --- |
| Account lifecycle | Yes | Yes | Yes | `Account lifecycle` marker |
| Profile | Yes | Yes | Yes | `Profile` marker |
| DMs | Yes | Yes | Yes | `DMs` marker |
| Rooms | Yes | Yes | Yes | `Rooms` marker |
| Timeline | Yes | Yes | Yes | `Timeline` marker |
| Pruning recovery UX | Yes | Yes | Yes | `Pruning recovery UX` marker |
| OWASP ASVS baseline | Yes | Yes | Yes | `OWASP ASVS` marker |
| WCAG keyboard baseline | Yes | Yes | N/A (TUI keyboard-native) | `WCAG 2.x` marker |

## Minimum artifact bundle for release review
- `ROADMAP.md` section for Phase 5.2 with no missing headings.
- `clients/docs/production_clients_exit_criteria.md` current revision.
- Web manual smoke log with timestamps and environment details.
- TUI manual smoke log with timestamps and environment details.
- Automated contract test output for roadmap/spec markers.
- Security checklist result with sign-off owner/date.
- Accessibility checklist result with sign-off owner/date.

## Manual smoke template (copy/paste)

### Environment
- Date/time:
- Commit SHA:
- Gateway mode (sqlite/memory):
- Client variant (web/tui):

### Account lifecycle
- Start/auth result:
- Resume result:
- Sign-out result:
- Notes:

### Profile
- Load result:
- Edit/publish result:
- Error-path validation:
- Notes:

### DMs
- Open/create result:
- Send/echo result:
- Replay result:
- Pruning recovery result:
- Notes:

### Rooms
- Create/open result:
- Invite/remove result:
- Send/echo result:
- Replay result:
- Notes:

### Timeline
- Fetch result:
- Publish result:
- Profile navigation result:
- Notes:

### Security + accessibility spot checks
- Security checklist deltas:
- Accessibility checklist deltas:
- Follow-up actions:

## Non-goals / out of scope
- No redesign/refactor of gateway protocol for this phase definition.
- No Node/npm-based UI framework adoption.
- No federation-specific UX guarantees beyond existing v1 constraints.
- No full visual polish requirements beyond functional production gates.
