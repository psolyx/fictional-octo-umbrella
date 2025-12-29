#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <pr_number> <iteration> [log_path|-]" >&2
  exit 1
fi

PR_NUMBER="$1"
ITERATION="$2"
LOG_SOURCE="${3:--}"

if [[ "$LOG_SOURCE" == "-" ]]; then
  LOG_FILE="$(mktemp)"
  cat >"$LOG_FILE"
else
  LOG_FILE="$LOG_SOURCE"
fi

if [[ ! -f "$LOG_FILE" ]]; then
  echo "Log file not found: $LOG_FILE" >&2
  exit 1
fi

{
  cat <<PROMPT
Open and follow .codex/skills/pr-fixloop/SKILL.md (copy constraints).
Return ONLY a unified diff patch in a \`\`\`diff fenced block\`\`\` that I can apply with git apply.

Goal: make ALLOW_AIOHTTP_STUB=0 make -C gateway check pass for PR #${PR_NUMBER}.
You are iteration ${ITERATION} of an automated loop. Keep edits minimal and deterministic.

Constraints:
- Do not modify .github/workflows/ci.yml or post PR comments.
- Do not rename/change any existing CI workflow/job identifiers (status contexts are branch-protection-critical).
- Do not add new system/package dependencies or apt-get installs.
- Preserve gateway invariants: monotonic seq per conv_id, (conv_id,msg_id) idempotency, echo-before-apply, deterministic replay/cursor semantics.
- Avoid protocol key typos: resume_token, next_seq, conv_id, msg_id, from_seq, after_seq mapping.
- Keep changes scoped to making checks pass; prefer code edits guided by the logs over rerunning heavy commands inside the sandbox.
PROMPT

  echo
  echo "Recent failing output (tail -n 250):"
  echo '```'
  tail -n 250 "$LOG_FILE"
  echo '```'
}

if [[ "$LOG_SOURCE" == "-" ]]; then
  rm -f "$LOG_FILE"
fi
