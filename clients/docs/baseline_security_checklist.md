SECURITY_CHECKLIST_V1

# Baseline security checklist (Phase 5.2)

This checklist is a static, auditable baseline for existing Phase 5.2 behavior across gateway + web + TUI.

## Session lifecycle + redaction safety
- [x] Session lifecycle operations are present for clients and gateway surface:
  - `GET /v1/session/list`
  - `POST /v1/session/revoke`
  - `POST /v1/session/logout_all`
- [x] Session lifecycle UI/status surfaces are redaction-safe (no raw `session_token`/`resume_token` display).

## Token storage constraints (web + TUI)
- [x] Web client stores session context only in browser-local state/storage needed for resume/session operations.
- [x] TUI client stores session context in local client state needed for restart/resume.
- [x] Tokens MUST NOT appear in:
  - user-facing status banners
  - debug/status logs
  - rendered list summaries in web account/session views

## Secret redaction invariants
- [x] No `st_` or `rt_` token-like literals appear in web log/status string literal paths.
- [x] TUI status output paths call `redact_text(...)` before user-visible output.

## HTTP error semantics
- [x] `401 unauthorized` responses include `WWW-Authenticate: Bearer`.
- [x] Unauthorized responses are marked `Cache-Control: no-store`.
- [x] `429` rate limit responses include `retry_after_s` JSON field and `Retry-After` header when bounded delay is known.
- [x] Web client parses/uses `retry_after_s` and `Retry-After` to enforce cooldown UX.

## Input validation posture
- [x] Invalid request semantics use deterministic `invalid_request` code + message contract.
- [x] Web profile/conversation text fields use `aria-invalid` markers on invalid form state.

## Audit command
- [x] `env PYTHONPATH=clients/cli/src python -m cli_app.phase5_2_static_audit_main`
  - Required pass markers:
    - `PHASE5_2_STATIC_AUDIT_BEGIN`
    - `PHASE5_2_STATIC_AUDIT_OK`
    - `PHASE5_2_STATIC_AUDIT_END`
