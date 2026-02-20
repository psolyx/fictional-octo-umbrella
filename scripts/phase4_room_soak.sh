#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

usage() {
  cat <<'USAGE'
Usage: scripts/phase4_room_soak.sh [duration_s] [msg_count] [members] [output_dir]

Optional environment:
  RUN_SLOW_TESTS=1   Run larger room-fanout profile in test_room_fanout_load_lite.

This operator script is intentionally NOT part of CI gates.
It runs existing Phase 4 harness-backed tests and writes logs to output_dir.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

DURATION_S="${1:-3600}"
MSG_COUNT="${2:-6000}"
MEMBERS="${3:-1000}"
OUT_DIR="${4:-artifacts/phase4_soak}"

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROOM_LOG="$OUT_DIR/room_fanout_${STAMP}.log"
DM_LOG="$OUT_DIR/dm_scaled_${STAMP}.log"

{
  echo "# Phase 4 operator soak"
  echo "duration_s=$DURATION_S"
  echo "msg_count=$MSG_COUNT"
  echo "members=$MEMBERS"
  echo "run_slow_tests=${RUN_SLOW_TESTS:-0}"
  echo "timestamp_utc=$STAMP"
} | tee "$OUT_DIR/profile_${STAMP}.txt"

STATUS="PASS"

if ! RUN_SLOW_TESTS="${RUN_SLOW_TESTS:-1}" python -m unittest -v gateway.tests.test_room_fanout_load_lite >"$ROOM_LOG" 2>&1; then
  STATUS="FAIL"
fi

if ! RUN_SLOW_TESTS="${RUN_SLOW_TESTS:-1}" python -m unittest -v gateway.tests.test_mls_dm_over_ds >"$DM_LOG" 2>&1; then
  STATUS="FAIL"
fi

cat <<PASTE
PASTE BEGIN
phase4_soak status=$STATUS duration_s=$DURATION_S msg_count=$MSG_COUNT members=$MEMBERS room_log=$ROOM_LOG dm_log=$DM_LOG
PASTE END
PASTE

if [[ "$STATUS" != "PASS" ]]; then
  exit 1
fi
