#!/usr/bin/env bash
set -euo pipefail

PR_NUMBER="${1:-}"
LOG_PATH="${2:-/tmp/pr-check.log}"
PROMPT_PATH="${3:-/tmp/pr-fix-prompt.md}"

if [[ -z "$PR_NUMBER" ]]; then
  echo "Usage: $0 <pr_number> [log_path] [prompt_path]" >&2
  exit 1
fi

CHECK_LOG="$LOG_PATH"
FORBIDDEN_FILES=(".github/workflows/ci.yml")

run_checks() {
  : >"$CHECK_LOG"
  if ! python -m compileall . >>"$CHECK_LOG" 2>&1; then
    return 1
  fi

  if grep -R -nE 'resumeToken|nextSeq|fromSeq|convId|msgId' gateway clients >>"$CHECK_LOG" 2>&1; then
    echo "Forbidden camelCase protocol keys detected; use snake_case variants (resume_token, next_seq, from_seq, conv_id, msg_id)." >>"$CHECK_LOG"
    return 1
  fi

  if ALLOW_AIOHTTP_STUB=0 make -C gateway check >>"$CHECK_LOG" 2>&1; then
    return 0
  fi
  return 1
}

ensure_forbidden_clean() {
  for path in "${FORBIDDEN_FILES[@]}"; do
    if [[ -n $(git status --porcelain -- "$path") ]]; then
      echo "Forbidden file modified: $path" >&2
      git checkout -- "$path"
      exit 1
    fi
  done
}

ensure_forbidden_clean

if run_checks; then
  echo "Checks passed" >&2
  exit 0
fi

scripts/gen_codex_prompt.sh "$PR_NUMBER" 1 "$CHECK_LOG" >"$PROMPT_PATH"

echo "Checks failed; prompt written to $PROMPT_PATH" >&2
exit 1
