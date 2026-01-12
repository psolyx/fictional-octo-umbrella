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

python -m cli_app.mls_poc --profile alice gw-dm-send \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/alice" \
  --plaintext "${PLAINTEXT}" >/dev/null

cat <<OUTPUT
=== WEB IMPORT (paste into DM UI) ===
welcome_env_b64=${WELCOME_ENV_B64}
commit_env_b64=${COMMIT_ENV_B64}
app_env_b64=${APP_ENV_B64}
expected_plaintext=${PLAINTEXT}
====================================
OUTPUT
