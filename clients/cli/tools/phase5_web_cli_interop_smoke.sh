#!/usr/bin/env bash
set -euo pipefail

# Manual smoke (run against a running gateway):
#   GW_BASE_URL=https://gateway.local \
#     ./clients/cli/tools/phase5_web_cli_interop_smoke.sh
# Then in the web DM import UI:
#   1) Load welcome env → Join
#   2) Load commit env → Apply commit
#   3) Load app env → Decrypt (must match expected_plaintext)

if [[ -z "${GW_BASE_URL:-}" ]]; then
  echo "GW_BASE_URL is required (example: https://gateway.local)" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)

export PYTHONPATH="${PYTHONPATH:-}:${REPO_ROOT}/clients/cli/src"

PROFILE_HOME="${REPO_ROOT}/clients/cli/profiles/phase5_web_cli_interop"
STATE_BASE="${PROFILE_HOME}/state"
mkdir -p "${STATE_BASE}"
export HOME="${PROFILE_HOME}"

PLAINTEXT="phase5 cli to web interop"
DM_SEED=5505
KP_SEED_BASE=6100

python -m cli_app.mls_poc --profile alice whoami >/dev/null
python -m cli_app.mls_poc --profile bob whoami >/dev/null

for profile in alice bob; do
  python -m cli_app.mls_poc --profile "${profile}" gw-start --base-url "${GW_BASE_URL}"
done

python -m cli_app.mls_poc --profile bob gw-kp-publish \
  --count 1 \
  --state-dir "${STATE_BASE}/bob" \
  --name "bob" \
  --seed-base "${KP_SEED_BASE}" >/dev/null

BOB_USER_ID=$(python - <<'PY'
from cli_app.identity_store import load_or_create_identity
from cli_app.profile_paths import resolve_profile_paths
identity = load_or_create_identity(resolve_profile_paths("bob").identity_path)
print(identity.user_id)
PY
)

CONV_ID=$(python - <<'PY'
import base64
import hashlib
seed = b"phase5-web-cli-interop-conv"
digest = hashlib.sha256(seed).digest()[:16]
print(base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="))
PY
)

GROUP_ID=$(python - <<'PY'
import base64
import hashlib
seed = b"phase5-web-cli-interop-group"
digest = hashlib.sha256(seed).digest()[:32]
print(base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="))
PY
)

PEER_KP=$(python -m cli_app.mls_poc --profile alice gw-kp-fetch \
  --user-id "${BOB_USER_ID}" \
  --count 1 | head -n 1)

python -m cli_app.mls_poc --profile alice gw-dm-create \
  --conv-id "${CONV_ID}" \
  --peer-user-id "${BOB_USER_ID}" >/dev/null

python -m cli_app.mls_poc --profile alice gw-dm-init-send \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/alice" \
  --peer-kp-b64 "${PEER_KP}" \
  --group-id "${GROUP_ID}" \
  --seed "${DM_SEED}" >/dev/null

rm -rf "${STATE_BASE}/alice_env"
DM_INIT_JSON=$(python -m cli_app.mls_poc dm-init \
  --state-dir "${STATE_BASE}/alice_env" \
  --peer-keypackage "${PEER_KP}" \
  --group-id "${GROUP_ID}" \
  --seed "${DM_SEED}")

WELCOME_ENV_B64=$(printf '%s' "${DM_INIT_JSON}" | python - <<'PY'
import json
import sys
from cli_app import dm_envelope
payload = json.loads(sys.stdin.read())
print(dm_envelope.pack(0x01, payload["welcome"]))
PY
)

COMMIT_ENV_B64=$(printf '%s' "${DM_INIT_JSON}" | python - <<'PY'
import json
import sys
from cli_app import dm_envelope
payload = json.loads(sys.stdin.read())
print(dm_envelope.pack(0x02, payload["commit"]))
PY
)

rm -rf "${STATE_BASE}/alice_app_env"
cp -a "${STATE_BASE}/alice" "${STATE_BASE}/alice_app_env"
CIPHERTEXT_B64=$(python -m cli_app.mls_poc dm-encrypt \
  --state-dir "${STATE_BASE}/alice_app_env" \
  --plaintext "${PLAINTEXT}" | head -n 1)

APP_ENV_B64=$(printf '%s' "${CIPHERTEXT_B64}" | python - <<'PY'
import sys
from cli_app import dm_envelope
print(dm_envelope.pack(0x03, sys.stdin.read().strip()))
PY
)

EXPECTED_APP_MSG_ID_HEX=$(printf '%s' "${APP_ENV_B64}" | python - <<'PY'
import base64
import hashlib
import sys

env_b64 = sys.stdin.read().strip()
padding = "=" * (-len(env_b64) % 4)
env_bytes = base64.urlsafe_b64decode(env_b64 + padding)
print(hashlib.sha256(env_bytes).hexdigest())
PY
)

python -m cli_app.mls_poc --profile alice gw-dm-send \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/alice" \
  --plaintext "${PLAINTEXT}" >/dev/null

readarray -t transcript_info < <(
  APP_ENV_B64="${APP_ENV_B64}" \
  COMMIT_ENV_B64="${COMMIT_ENV_B64}" \
  EXPECTED_APP_MSG_ID_HEX="${EXPECTED_APP_MSG_ID_HEX}" \
  PLAINTEXT="${PLAINTEXT}" \
  WELCOME_ENV_B64="${WELCOME_ENV_B64}" \
  python - <<'PY'
import base64
import hashlib
import json
import os
import time
from pathlib import Path

from cli_app import gateway_client, gateway_store, identity_store, profile_paths

conv_id = os.environ["CONV_ID"]
profile = "alice"
timeout_s = 15.0
max_events = 50
expected_plaintext = os.environ["PLAINTEXT"]
expected_app_msg_id_hex = os.environ["EXPECTED_APP_MSG_ID_HEX"]
welcome_env_b64 = os.environ["WELCOME_ENV_B64"]
commit_env_b64 = os.environ["COMMIT_ENV_B64"]
app_env_b64 = os.environ["APP_ENV_B64"]

paths = profile_paths.resolve_profile_paths(profile)
identity_store.load_or_create_identity(paths.identity_path)
session = gateway_store.load_session(paths.session_path)
if session is None:
    raise SystemExit("No gateway session found for transcript fetch.")

base_url = os.environ.get("GW_BASE_URL", session["base_url"])
events_by_seq = {}
seen_welcome = False
seen_commit = False
seen_app = False
matched_app_msg = False
start = time.monotonic()

from typing import Optional

def decode_env_kind(env_b64: str) -> Optional[int]:
    try:
        padding = "=" * (-len(env_b64) % 4)
        env_bytes = base64.urlsafe_b64decode(env_b64 + padding)
    except Exception:
        return None
    if not env_bytes:
        return None
    return env_bytes[0]

for event in gateway_client.sse_tail(
    base_url,
    session["session_token"],
    conv_id,
    1,
    idle_timeout_s=timeout_s,
):
    if time.monotonic() - start > timeout_s:
        break
    if not isinstance(event, dict) or event.get("t") != "conv.event":
        continue
    body = event.get("body", {})
    if not isinstance(body, dict):
        continue
    seq = body.get("seq")
    env = body.get("env")
    msg_id = body.get("msg_id") if isinstance(body.get("msg_id"), str) else None
    if not isinstance(seq, int) or not isinstance(env, str):
        continue
    events_by_seq.setdefault(seq, {"seq": seq, "msg_id": msg_id, "env": env})
    kind = decode_env_kind(env)
    if kind == 0x01:
        seen_welcome = True
    elif kind == 0x02:
        seen_commit = True
    elif kind == 0x03:
        seen_app = True
        if msg_id is None:
            raise SystemExit(
                "Replay app envelope missing msg_id; cannot validate deterministic msg_id."
            )
        if msg_id == expected_app_msg_id_hex:
            matched_app_msg = True
    if len(events_by_seq) >= max_events:
        break
    if seen_welcome and seen_commit and matched_app_msg:
        break

if not seen_welcome:
    raise SystemExit("Replay did not include a welcome (kind=1) envelope before timeout.")
if not seen_commit:
    raise SystemExit("Replay did not include a commit (kind=2) envelope before timeout.")
if not seen_app:
    raise SystemExit("Replay did not include an app (kind=3) envelope before timeout.")
if not matched_app_msg:
    raise SystemExit(
        "Replay did not include app envelope with expected msg_id; verify the send or increase timeout."
    )

events = list(events_by_seq.values())
events.sort(key=lambda entry: entry["seq"])
canonical_events = [
    {"seq": entry["seq"], "msg_id": entry["msg_id"], "env": entry["env"]}
    for entry in events
]
canonical_payload = {
    "schema_version": 1,
    "conv_id": conv_id,
    "from_seq": 1,
    "next_seq": None,
    "events": canonical_events,
}
canonical_json = json.dumps(canonical_payload, separators=(",", ":"), ensure_ascii=False)
digest = hashlib.sha256(canonical_json.encode("utf-8")).digest()
digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
payload = dict(canonical_payload)
payload["digest_sha256_b64"] = digest_b64
payload["expected_plaintext"] = expected_plaintext
payload["expected_app_msg_id_hex"] = expected_app_msg_id_hex
payload["welcome_env_b64"] = welcome_env_b64
payload["commit_env_b64"] = commit_env_b64
payload["app_env_b64"] = app_env_b64

profile_home = Path(os.environ["HOME"])
transcript_path = profile_home / "transcript.json"
transcript_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
print(str(transcript_path.resolve()))
print(digest_b64)
PY
)
TRANSCRIPT_PATH=${transcript_info[0]}
TRANSCRIPT_DIGEST_SHA256_B64=${transcript_info[1]}

cat <<OUTPUT
=== WEB IMPORT (paste into DM UI) ===
welcome_env_b64=${WELCOME_ENV_B64}
commit_env_b64=${COMMIT_ENV_B64}
app_env_b64=${APP_ENV_B64}
expected_plaintext=${PLAINTEXT}
expected_app_msg_id_hex=${EXPECTED_APP_MSG_ID_HEX}
transcript_digest_sha256_b64=${TRANSCRIPT_DIGEST_SHA256_B64}
transcript_path=${TRANSCRIPT_PATH}
====================================
OUTPUT
