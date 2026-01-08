#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${GW_BASE_URL:-}" ]]; then
  echo "GW_BASE_URL is required (example: https://gateway.local)" >&2
  exit 1
fi

export PYTHONPATH="${PYTHONPATH:-}:clients/cli/src"

STATE_BASE="${STATE_BASE:-/tmp/polycentric_phase2}"
mkdir -p "${STATE_BASE}"

profiles=(u1d1 u1d2 u2d1 u2d2)

python -m cli_app.mls_poc --profile u1d1 whoami >/dev/null
python -m cli_app.mls_poc --profile u2d1 whoami >/dev/null

python - <<'PY'
import shutil
from cli_app.identity_store import rotate_device
from cli_app.profile_paths import resolve_profile_paths

def clone_device(source: str, target: str) -> None:
    source_path = resolve_profile_paths(source).identity_path
    target_path = resolve_profile_paths(target).identity_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    rotate_device(target_path)

clone_device("u1d1", "u1d2")
clone_device("u2d1", "u2d2")
PY

for profile in "${profiles[@]}"; do
  python -m cli_app.mls_poc --profile "${profile}" gw-start --base-url "${GW_BASE_URL}"
  python -m cli_app.mls_poc --profile "${profile}" gw-kp-publish \
    --count 2 \
    --state-dir "${STATE_BASE}/${profile}" \
    --name "${profile}" \
    --seed-base 1000
  echo "Session and KeyPackages ready for ${profile}."
done

U2_USER_ID=$(python - <<'PY'
from cli_app.identity_store import load_or_create_identity
from cli_app.profile_paths import resolve_profile_paths
identity = load_or_create_identity(resolve_profile_paths("u2d1").identity_path)
print(identity.user_id)
PY
)

CONV_ID=$(python - <<'PY'
import base64
import os
print(base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("="))
PY
)

GROUP_ID=$(python - <<'PY'
import base64
import os
print(base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("="))
PY
)

PEER_KP=$(python -m cli_app.mls_poc --profile u1d1 gw-kp-fetch \
  --user-id "${U2_USER_ID}" \
  --count 1 | head -n 1)

python -m cli_app.mls_poc --profile u1d1 gw-dm-create \
  --conv-id "${CONV_ID}" \
  --peer-user-id "${U2_USER_ID}"

python -m cli_app.mls_poc --profile u1d1 gw-dm-init-send \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/u1d1" \
  --peer-kp-b64 "${PEER_KP}" \
  --group-id "${GROUP_ID}"

python -m cli_app.mls_poc --profile u2d1 gw-dm-tail \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/u2d1"

python -m cli_app.mls_poc --profile u1d1 gw-dm-send \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/u1d1" \
  --plaintext "hello from u1d1"

python -m cli_app.mls_poc --profile u2d1 gw-dm-tail \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/u2d1"

python - <<'PY'
from cli_app import gateway_store
from cli_app.profile_paths import resolve_profile_paths

paths = resolve_profile_paths("u2d1")
stored = gateway_store.load_session(paths.session_path)
if stored is None:
    raise SystemExit("u2d1 session file missing; run gw-start first")
gateway_store.save_session(stored["base_url"], "", stored["resume_token"], paths.session_path)
PY

python -m cli_app.mls_poc --profile u2d1 gw-resume --base-url "${GW_BASE_URL}"
python -m cli_app.mls_poc --profile u2d1 gw-dm-tail \
  --conv-id "${CONV_ID}" \
  --state-dir "${STATE_BASE}/u2d1"
