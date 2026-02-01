#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8787}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8787}"
DB="${DB:-/tmp/gateway.sqlite}"
PY="${PY:-gateway/.venv/bin/python}"

# reuse one conv_id across restarts so we can replay
CONV_ID="${CONV_ID:-c_demo_$(date +%s)}"

die(){ echo "ERROR: $*" >&2; exit 1; }

start_gw () {
  PYTHONPATH=gateway/src "$PY" -m gateway.server serve --host "$HOST" --port "$PORT" --db "$DB" &
  GW_PID=$!
  for _ in $(seq 1 80); do
    curl -fsS "$BASE/healthz" >/dev/null && return 0
    sleep 0.1
  done
  kill "$GW_PID" 2>/dev/null || true
  die "gateway did not become healthy at $BASE"
}

stop_gw () {
  kill "$GW_PID" 2>/dev/null || true
  wait "$GW_PID" 2>/dev/null || true
}

command -v curl >/dev/null || die "curl missing"
[[ -x "$PY" ]] || die "venv python missing at $PY (run: make -C gateway setup)"

rm -f "$DB"
start_gw
CONV_ID="$CONV_ID" ./scripts/local_ws_smoke.sh
stop_gw

start_gw
CONV_ID="$CONV_ID" ./scripts/local_ws_smoke.sh
stop_gw

echo "OK: full smoke (start -> ws -> restart -> ws) complete"


