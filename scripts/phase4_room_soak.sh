#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

usage() {
  cat <<'USAGE'
Usage: scripts/phase4_room_soak.sh [duration_s] [msg_rate] [members] [output_dir]

Optional environment:
  RUN_SLOW_TESTS=1   Run larger non-soak profile in selected harness-backed tests.
  RUN_SOAK_TESTS=1   Permit large room profile values without script auto-detection.

This operator script is intentionally NOT part of CI gates.
It runs existing Phase 4 harness-backed tests and writes logs to output_dir.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

DURATION_S="${1:-60}"
MSG_RATE="${2:-2}"
MEMBERS="${3:-200}"
OUT_DIR="${4:-artifacts/phase4_soak}"
RUN_SLOW_TESTS="${RUN_SLOW_TESTS:-0}"

if ! [[ "$DURATION_S" =~ ^[0-9]+$ ]]; then
  echo "duration_s must be an integer" >&2
  exit 2
fi
if ! [[ "$MSG_RATE" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "msg_rate must be a non-negative number" >&2
  exit 2
fi
if ! [[ "$MEMBERS" =~ ^[0-9]+$ ]]; then
  echo "members must be an integer" >&2
  exit 2
fi

MSG_COUNT="$(python - <<'PY' "$DURATION_S" "$MSG_RATE"
import sys

duration_s = int(sys.argv[1])
msg_rate = float(sys.argv[2])
print(max(1, int(round(duration_s * msg_rate))))
PY
)"

SCRIPT_SET_SOAK=0
if (( DURATION_S > 300 || MEMBERS > 200 || MSG_COUNT > 1200 )); then
  SCRIPT_SET_SOAK=1
fi

if [[ "${RUN_SOAK_TESTS:-0}" == "1" ]]; then
  SCRIPT_SET_SOAK=1
fi

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ROOM_LOG="$OUT_DIR/room_fanout_${STAMP}.log"
DM_LOG="$OUT_DIR/dm_scaled_${STAMP}.log"

{
  echo "# Phase 4 operator soak"
  echo "duration_s=$DURATION_S"
  echo "msg_rate=$MSG_RATE"
  echo "msg_count=$MSG_COUNT"
  echo "members=$MEMBERS"
  echo "run_slow_tests=$RUN_SLOW_TESTS"
  echo "run_soak_tests=$SCRIPT_SET_SOAK"
  echo "timestamp_utc=$STAMP"
} | tee "$OUT_DIR/profile_${STAMP}.txt"

STATUS="PASS"

if ! (
  cd gateway
  PYTHONPATH="src:${PYTHONPATH:-}" \
    RUN_SLOW_TESTS="$RUN_SLOW_TESTS" \
    ROOM_DURATION_S="$DURATION_S" \
    ROOM_MSG_RATE="$MSG_RATE" \
    ROOM_MSG_COUNT="$MSG_COUNT" \
    ROOM_MEMBERS="$MEMBERS" \
    RUN_SOAK_TESTS="$SCRIPT_SET_SOAK" \
    python -m unittest -v tests.test_room_fanout_load_lite
) >"$ROOM_LOG" 2>&1; then
  STATUS="FAIL"
fi

if ! (cd gateway && PYTHONPATH="src:${PYTHONPATH:-}" RUN_SLOW_TESTS="$RUN_SLOW_TESTS" python -m unittest -v tests.test_mls_dm_over_ds) >"$DM_LOG" 2>&1; then
  STATUS="FAIL"
fi

cat <<PASTE
PASTE BEGIN
phase4_soak status=$STATUS duration_s=$DURATION_S msg_rate=$MSG_RATE msg_count=$MSG_COUNT members=$MEMBERS run_soak_tests=$SCRIPT_SET_SOAK room_log=$ROOM_LOG dm_log=$DM_LOG
PASTE END
PASTE

if [[ "$STATUS" != "PASS" ]]; then
  exit 1
fi
