#!/usr/bin/env bash
set -euo pipefail

# local_ws_smoke.sh
# Smoke test for gateway WebSocket /v1/ws end-to-end:
# - HTTP: session/start -> rooms/create
# - WS: session.resume -> session.ready
# - WS: conv.subscribe(from_seq=1)
# - WS: conv.send -> conv.acked AND conv.event observed
#
# Run from repo root (recommended):
#   bash /path/to/local_ws_smoke.sh
#
# Assumes gateway is already running at BASE (default http://127.0.0.1:8787)
# and the gateway venv exists at gateway/.venv (created by `make -C gateway setup`).
#
# Optional env overrides:
#   BASE=http://127.0.0.1:8787
#   AUTH_TOKEN="Bearer user1"
#   DEVICE_ID="device-1"
#   DEVICE_CREDENTIAL="cred"
#   CONV_ID="c_demo"          # default is unique c_demo_<epoch>
#   MSG_ID="ws1"
#   ENV="hello over ws"
#   TIMEOUT_S=10
#   PY=/path/to/gateway/.venv/bin/python

BASE="${BASE:-http://127.0.0.1:8787}"
AUTH_TOKEN="${AUTH_TOKEN:-Bearer user1}"
DEVICE_ID="${DEVICE_ID:-device-1}"
DEVICE_CREDENTIAL="${DEVICE_CREDENTIAL:-cred}"
TIMEOUT_S="${TIMEOUT_S:-10}"

CONV_ID="${CONV_ID:-c_demo_$(date +%s)}"
MSG_ID="${MSG_ID:-ws_smoke_1}"
ENV="${ENV:-hello over ws}"

PY="${PY:-gateway/.venv/bin/python}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -x "$PY" ]] || die "gateway venv python not found/executable at: $PY (run: make -C gateway setup)"
command -v curl >/dev/null || die "curl not found"
command -v python3 >/dev/null || die "system python3 not found"

# Health check
curl -fsS "$BASE/healthz" >/dev/null || die "gateway not healthy at $BASE (is it running?)"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT


# Build JSON payloads safely with system python (avoids quoting issues).
export AUTH_TOKEN DEVICE_ID DEVICE_CREDENTIAL CONV_ID
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
curl -fsS -X POST "$BASE/v1/session/start"   -H 'Content-Type: application/json'   -d "$SESSION_START_JSON"
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


room_create_code="$(
curl -sS -o "$tmpdir/room_create.json" -w '%{http_code}'   -X POST "$BASE/v1/rooms/create"   -H "Authorization: Bearer $SESSION_TOKEN"   -H 'Content-Type: application/json'   -d "$ROOM_CREATE_JSON" || true
)"

if [[ "$room_create_code" == "200" || "$room_create_code" == "201" ]]; then
  echo "created room: $CONV_ID"
elif [[ "$room_create_code" == "400" ]] && grep -qi 'conversation already exists' "$tmpdir/room_create.json"; then
  echo "room already exists: $CONV_ID"
else
  echo "room create failed (HTTP $room_create_code): $(cat "$tmpdir/room_create.json" 2>/dev/null || true)" >&2
  exit 1
fi


BASE="$BASE" CONV_ID="$CONV_ID" RESUME_TOKEN="$RESUME_TOKEN" MSG_ID="$MSG_ID" ENV="$ENV" TIMEOUT_S="$TIMEOUT_S" "$PY" - <<'PY'
import asyncio, os, sys
import aiohttp

BASE = os.environ["BASE"]
CONV_ID = os.environ["CONV_ID"]
RESUME_TOKEN = os.environ["RESUME_TOKEN"]
MSG_ID = os.environ["MSG_ID"]
ENV = os.environ["ENV"]
TIMEOUT_S = float(os.environ.get("TIMEOUT_S", "10"))

def http_to_ws(url: str) -> str:
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):]
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):]
    return url

WS_URL = http_to_ws(BASE.rstrip("/")) + "/v1/ws"

async def run() -> int:
    got_ready = False
    got_acked = False
    got_event = False

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS_URL, autoping=False) as ws:
            await ws.send_json({"v": 1, "t": "session.resume", "id": "hs1", "body": {"resume_token": RESUME_TOKEN}})

            deadline = asyncio.get_event_loop().time() + TIMEOUT_S

            async def recv_json():
                while True:
                    remaining = max(0.0, deadline - asyncio.get_event_loop().time())
                    if remaining == 0.0:
                        raise asyncio.TimeoutError("timeout")
                    msg = await ws.receive(timeout=remaining)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        return msg.json()
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        raise RuntimeError(f"websocket closed: {msg.type}")

            # handshake
            while True:
                frame = await recv_json()
                t = frame.get("t")
                if t == "ping":
                    await ws.send_json({"v": 1, "t": "pong"})
                    continue
                if t == "error":
                    raise RuntimeError(f"server error during handshake: {frame}")
                if t == "session.ready":
                    got_ready = True
                    break

            await ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub1", "body": {"conv_id": CONV_ID, "from_seq": 1}})
            await ws.send_json({"v": 1, "t": "conv.send", "id": "send1", "body": {"conv_id": CONV_ID, "msg_id": MSG_ID, "env": ENV}})

            while asyncio.get_event_loop().time() < deadline:
                frame = await recv_json()
                t = frame.get("t")
                if t == "ping":
                    await ws.send_json({"v": 1, "t": "pong"})
                    continue
                if t == "error":
                    raise RuntimeError(f"server error: {frame}")
                if t == "conv.acked" and frame.get("body", {}).get("conv_id") == CONV_ID:
                    got_acked = True
                if t == "conv.event" and frame.get("body", {}).get("conv_id") == CONV_ID:
                    got_event = True
                if got_acked and got_event:
                    break

    if not got_ready:
        print("FAIL: did not receive session.ready", file=sys.stderr)
        return 1
    if not got_acked:
        print("FAIL: did not receive conv.acked", file=sys.stderr)
        return 1
    if not got_event:
        print("FAIL: did not receive conv.event", file=sys.stderr)
        return 1

    print("OK: ws handshake + subscribe + send + event observed")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
PY

echo "OK: local_ws_smoke.sh complete"
