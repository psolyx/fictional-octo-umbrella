#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# local_http_sse_smoke.sh
#
# Single-terminal HTTP + SSE smoke:
#   - POST /v1/session/start
#   - POST /v1/rooms/create
#   - GET  /v1/sse?conv_id=...&from_seq=...
#   - POST /v1/inbox (conv.send frames)
#
# Defaults are geared for local Fedora runs with the gateway on 127.0.0.1:8787.

BASE="${BASE:-${GW_BASE_URL:-http://127.0.0.1:8787}}"
AUTH_TOKEN="${AUTH_TOKEN:-Bearer user1}"
DEVICE_ID="${DEVICE_ID:-device-1}"
DEVICE_CREDENTIAL="${DEVICE_CREDENTIAL:-cred}"

CONV_ID="${CONV_ID:-c_http_sse_$(date +%s)}"
EVENTS_N="${EVENTS_N:-3}"

# Inclusive resume semantics: from_seq is inclusive.
FROM_SEQ="${FROM_SEQ:-1}"

# If REPLAY=1, the script will NOT POST new inbox messages; it only verifies SSE replay.
REPLAY="${REPLAY:-0}"

# How long to wait for the expected seqs to appear in the SSE log.
WAIT_S="${WAIT_S:-10}"

# Where to write the SSE output.
SSE_LOG="${SSE_LOG:-/tmp/sse_${CONV_ID}.log}"

die(){ echo "ERROR: $*" >&2; exit 1; }

command -v curl >/dev/null || die "curl not found"
command -v python3 >/dev/null || die "system python3 not found"

echo "[info] BASE=$BASE"
echo "[info] CONV_ID=$CONV_ID"
echo "[info] REPLAY=$REPLAY FROM_SEQ=$FROM_SEQ EVENTS_N=$EVENTS_N WAIT_S=$WAIT_S"
echo "[info] SSE_LOG=$SSE_LOG"

# Build JSON payloads safely with python (avoids quoting pitfalls).
export AUTH_TOKEN DEVICE_ID DEVICE_CREDENTIAL
SESSION_START_JSON="$(
python3 - <<'PY'
import json, os
payload = {
  "auth_token": os.environ["AUTH_TOKEN"],
  "device_id": os.environ["DEVICE_ID"],
  "device_credential": os.environ.get("DEVICE_CREDENTIAL"),
}
if payload["device_credential"] is None:
    payload.pop("device_credential")
print(json.dumps(payload))
PY
)"

st_json="$(
curl -fsS -X POST "$BASE/v1/session/start"   -H "Content-Type: application/json"   -d "$SESSION_START_JSON"
)"

SESSION_TOKEN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["session_token"])' <<<"$st_json")"
RESUME_TOKEN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["resume_token"])' <<<"$st_json")"

echo "session_token=$SESSION_TOKEN"
echo "resume_token=$RESUME_TOKEN"

ROOM_CREATE_JSON="$(
python3 - <<'PY'
import json, os
print(json.dumps({"conv_id": os.environ["CONV_ID"], "members": []}))
PY
)"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

# Room create is idempotent across restarts in this workflow (same conv_id reused).
# Treat 409/duplicate as OK (common on replay/restart).
code="$(
curl -sS -o "$tmpdir/room_create.json" -w '%{http_code}'   -X POST "$BASE/v1/rooms/create"   -H "Authorization: Bearer $SESSION_TOKEN"   -H "Content-Type: application/json"   -d "$ROOM_CREATE_JSON" || true
)"
if [[ "$code" == "200" || "$code" == "201" ]]; then
  echo "[info] room created: $CONV_ID"
elif [[ "$code" == "409" ]]; then
  echo "[info] room already exists (HTTP 409): $CONV_ID"
else
  # Some implementations may return 400 with a duplicate message; allow that too.
  if grep -qiE 'duplicate|already exists|conflict' "$tmpdir/room_create.json" 2>/dev/null; then
    echo "[info] room already exists (non-2xx): $CONV_ID"
  else
    echo "[warn] room create non-2xx (HTTP $code): $(cat "$tmpdir/room_create.json" 2>/dev/null || true)" >&2
    # For a fresh run, treat unexpected non-2xx as fatal.
    [[ "$REPLAY" == "1" ]] || die "room create failed unexpectedly"
  fi
fi

: > "$SSE_LOG"

cleanup_stream() {
  if [[ -n "${SSE_PID:-}" ]]; then
    kill "$SSE_PID" 2>/dev/null || true
    wait "$SSE_PID" 2>/dev/null || true
  fi
}
trap cleanup_stream EXIT

# -N/--no-buffer disables output buffering for streaming.
curl -sS -N --no-buffer -H "Authorization: Bearer $SESSION_TOKEN"   "$BASE/v1/sse?conv_id=$CONV_ID&from_seq=$FROM_SEQ" >>"$SSE_LOG" &
SSE_PID=$!
echo "[info] SSE_PID=$SSE_PID"

# Give the stream a moment to connect.
sleep 0.2
kill -0 "$SSE_PID" 2>/dev/null || die "SSE curl exited early; check $SSE_LOG"

if [[ "$REPLAY" != "1" ]]; then
  for i in $(seq 1 "$EVENTS_N"); do
    export CONV_ID i
    INBOX_JSON="$(
    python3 - <<'PY'
import json, os
conv_id = os.environ["CONV_ID"]
i = int(os.environ["i"])
payload = {"v": 1, "t": "conv.send", "body": {"conv_id": conv_id, "msg_id": f"m{i}", "env": f"msg {i}"}}
print(json.dumps(payload))
PY
    )"
    curl -fsS -X POST "$BASE/v1/inbox"       -H "Authorization: Bearer $SESSION_TOKEN"       -H "Content-Type: application/json"       -d "$INBOX_JSON" >/dev/null
  done
fi

# Wait until we see seqs [FROM_SEQ, FROM_SEQ + EVENTS_N - 1] in the SSE stream.
python3 - "$SSE_LOG" "$FROM_SEQ" "$EVENTS_N" "$WAIT_S" <<'PY' || {
import re, sys, time
path = sys.argv[1]
from_seq = int(sys.argv[2])
events_n = int(sys.argv[3])
wait_s = float(sys.argv[4])

need = set(range(from_seq, from_seq + events_n))
t0 = time.time()

def read_txt():
  try:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
      return f.read()
  except FileNotFoundError:
    return ""

while True:
  txt = read_txt()
  seqs = set(int(m) for m in re.findall(r'"seq"\s*:\s*(\d+)', txt))
  if need.issubset(seqs):
    sys.exit(0)
  if time.time() - t0 > wait_s:
    sys.exit(1)
  time.sleep(0.1)
PY
  echo "[info] SSE log (last 80 lines):" >&2
  tail -n 80 "$SSE_LOG" >&2 || true
  die "did not observe expected seq range in SSE within ${WAIT_S}s"
}

echo "[info] SSE log (last 50 lines):"
tail -n 50 "$SSE_LOG"

echo "[ok] http+sse smoke complete"
