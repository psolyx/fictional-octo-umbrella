#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# fullstack_smoke.sh
#
# Fedora-friendly local full-stack smoke:
#   1) Fast unit tests (gateway + CLI)
#   2) Build artifacts (WASM harness)
#   3) Bring up gateway
#   4) Non-UI API smokes (HTTP+SSE + WS)
#   5) CLI -> gateway integration smoke (stdlib client)
#   6) Restart gateway (same DB) and verify replay (SSE + WS)
#
# Run from repo root:
#   ./scripts/fullstack_smoke.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8787}"
BASE="${BASE:-${GW_BASE_URL:-http://$HOST:$PORT}}"
DB="${DB:-/tmp/gateway.sqlite}"

# Gateway python (venv) used to run the server.
PY="${PY:-$REPO_ROOT/gateway/.venv/bin/python}"

# Reuse one conv_id across restarts so we can verify replay.
CONV_ID="${CONV_ID:-c_fullstack_$(date +%s)}"

# Controls
SKIP_TESTS="${SKIP_TESTS:-0}"
SKIP_WASM="${SKIP_WASM:-0}"

die(){ echo "ERROR: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

need curl
need ss
need python3
need make

preflight_port() {
  if ss -ltnp | grep -q ":$PORT"; then
    ss -ltnp | grep ":$PORT" || true
    die "port $PORT already in use; stop the old gateway (e.g. sudo fuser -k ${PORT}/tcp)"
  fi
}

wait_health() {
  for _ in $(seq 1 200); do
    curl -fsS "$BASE/healthz" >/dev/null 2>&1 && return 0
    sleep 0.1
  done
  return 1
}

start_gw () {
  [[ -x "$PY" ]] || die "gateway venv python missing at $PY (run: make -C gateway setup)"
  PYTHONPATH=gateway/src "$PY" -m gateway.server serve --host "$HOST" --port "$PORT" --db "$DB"     >"$GW_LOG" 2>&1 &
  GW_PID=$!

  if ! wait_health; then
    tail -n 160 "$GW_LOG" >&2 || true
    die "gateway did not become healthy at $BASE"
  fi
}

stop_gw () {
  if [[ -n "${GW_PID:-}" ]]; then
    kill "$GW_PID" 2>/dev/null || true
    wait "$GW_PID" 2>/dev/null || true
    unset GW_PID
  fi
}

tmpdir="$(mktemp -d)"
GW_LOG="$tmpdir/gateway.log"
trap 'stop_gw; rm -rf "$tmpdir"' EXIT

echo "[info] repo=$REPO_ROOT"
echo "[info] base=$BASE db=$DB conv_id=$CONV_ID"

preflight_port

if [[ "$SKIP_TESTS" != "1" ]]; then
  echo "[step] fast unit tests"
  make -C "$REPO_ROOT/gateway" test
  make -C "$REPO_ROOT/clients/cli" test
fi

if [[ "$SKIP_WASM" != "1" ]]; then
  echo "[step] build WASM harness"
  chmod +x "$REPO_ROOT/tools/mls_harness/build_wasm.sh" || true
  "$REPO_ROOT/tools/mls_harness/build_wasm.sh"
fi

echo "[step] start gateway"
rm -f "$DB"
start_gw

echo "[step] non-UI API smokes"
CONV_ID="$CONV_ID" BASE="$BASE" "$REPO_ROOT/scripts/local_http_sse_smoke.sh"
CONV_ID="$CONV_ID" BASE="$BASE" "$REPO_ROOT/scripts/local_ws_smoke.sh"

echo "[step] CLI -> gateway integration smoke"
CONV_ID="$CONV_ID" BASE="$BASE" "$REPO_ROOT/scripts/cli_gateway_smoke.sh"

echo "[step] restart gateway and verify replay"
stop_gw

# Ensure we really freed the port.
for _ in $(seq 1 50); do
  if ! ss -ltnp | grep -q ":$PORT"; then break; fi
  sleep 0.1
done
preflight_port

start_gw

# Replay: from_seq is inclusive. Expect seq 1..3 again without sending anything new.
CONV_ID="$CONV_ID" BASE="$BASE" REPLAY=1 FROM_SEQ=1 EVENTS_N=3 "$REPO_ROOT/scripts/local_http_sse_smoke.sh"
CONV_ID="$CONV_ID" BASE="$BASE" "$REPO_ROOT/scripts/local_ws_smoke.sh"

echo "[ok] fullstack_smoke complete"
echo "[info] gateway log: $GW_LOG"
