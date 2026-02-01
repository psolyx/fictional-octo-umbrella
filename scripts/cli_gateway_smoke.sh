#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# cli_gateway_smoke.sh
#
# CLI -> gateway integration smoke (non-test path).
# Uses the stdlib gateway client used by the CLI codebase:
#   clients/cli/src/cli_app/gateway_client.py
#
# Requires a running gateway at BASE (default http://127.0.0.1:8787).

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${BASE:-${GW_BASE_URL:-http://127.0.0.1:8787}}"
CONV_ID="${CONV_ID:-c_cli_gw_$(date +%s)}"
EVENTS_N="${EVENTS_N:-3}"

die(){ echo "ERROR: $*" >&2; exit 1; }

command -v python3 >/dev/null || die "system python3 not found"
command -v curl >/dev/null || die "curl not found"

curl -fsS "$BASE/healthz" >/dev/null || die "gateway not healthy at $BASE (is it running?)"

export PYTHONPATH="${PYTHONPATH:-$REPO_ROOT/clients/cli/src}"
export BASE CONV_ID EVENTS_N

python3 - <<'PY'
import os
import sys

from cli_app import gateway_client as gc

base = os.environ["BASE"]
conv_id = os.environ["CONV_ID"]
events_n = int(os.environ["EVENTS_N"])

tokens = gc.session_start(base, auth_token="Bearer user1", device_id="device-1", device_credential="cred")
st = tokens["session_token"]

# Create room (tolerate duplicate on re-runs)
try:
    gc.room_create(base, st, conv_id=conv_id, members=[])
except Exception:
    pass

for i in range(1, events_n + 1):
    gc.inbox_send(base, st, conv_id=conv_id, msg_id=f"m{i}", env_b64=f"msg {i}")

seqs = set()
for frame in gc.sse_tail(base, st, conv_id=conv_id, from_seq=1, max_events=events_n * 2, idle_timeout_s=5):
    if frame.get("t") != "conv.event":
        continue
    body = frame.get("body") or {}
    if body.get("conv_id") != conv_id:
        continue
    try:
        seqs.add(int(body["seq"]))
    except Exception:
        # Don't hard fail on unexpected frame shapes; keep scanning.
        continue
    if len(seqs) >= events_n:
        break

missing = [n for n in range(1, events_n + 1) if n not in seqs]
if missing:
    raise SystemExit(f"missing expected seqs via SSE: {missing}; saw {sorted(seqs)}")

print("OK: cli->gateway integration smoke passed")
print(f"conv_id={conv_id}")
print(f"seqs={sorted(seqs)}")
PY
