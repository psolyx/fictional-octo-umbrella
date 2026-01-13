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
export CONV_ID

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

python -m cli_app.mls_poc --profile alice gw-dm-send \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/alice" \
  --plaintext "${PLAINTEXT}" >/dev/null

APP_ENV_B64="${APP_ENV_B64}" \
COMMIT_ENV_B64="${COMMIT_ENV_B64}" \
PLAINTEXT="${PLAINTEXT}" \
WELCOME_ENV_B64="${WELCOME_ENV_B64}" \
python - <<'PY'
import json
import os
from pathlib import Path

from cli_app import gateway_store, identity_store, profile_paths
from cli_app.interop_transcript import (
    canonicalize_transcript,
    capture_sse_transcript,
    compute_digest_sha256_b64,
    compute_msg_id_hex,
)

conv_id = os.environ["CONV_ID"]
profile = "alice"
expected_plaintext = os.environ["PLAINTEXT"]
welcome_env_b64 = os.environ["WELCOME_ENV_B64"]
commit_env_b64 = os.environ["COMMIT_ENV_B64"]
app_env_b64 = os.environ["APP_ENV_B64"]
expected_app_msg_id_hex = compute_msg_id_hex(app_env_b64)

paths = profile_paths.resolve_profile_paths(profile)
identity_store.load_or_create_identity(paths.identity_path)
session = gateway_store.load_session(paths.session_path)
if session is None:
    raise SystemExit("No gateway session found for transcript fetch.")

base_url = os.environ.get("GW_BASE_URL", session["base_url"])
events = capture_sse_transcript(
    base_url,
    session["session_token"],
    conv_id,
    from_seq=1,
    timeout_s=15.0,
    max_events=50,
    expected_app_msg_id_hex=expected_app_msg_id_hex,
)
canonical_payload = canonicalize_transcript(conv_id, 1, None, events)
digest_b64 = compute_digest_sha256_b64(canonical_payload)

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

print("=== WEB IMPORT (paste into DM UI) ===")
print(f"welcome_env_b64={welcome_env_b64}")
print(f"commit_env_b64={commit_env_b64}")
print(f"app_env_b64={app_env_b64}")
print(f"expected_plaintext={expected_plaintext}")
print(f"expected_app_msg_id_hex={expected_app_msg_id_hex}")
print(f"transcript_digest_sha256_b64={digest_b64}")
print(f"transcript_path={transcript_path.resolve()}")
print("====================================")
PY
