#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   EVID_DIR=./evidence/<bundle-path> ./scripts/phase5_2_signoff_verify.sh
#   ARCHIVE_PATH=./evidence/<bundle-path>.tgz ./scripts/phase5_2_signoff_verify.sh
env PYTHONPATH=clients/cli/src python -m cli_app.phase5_2_signoff_verify_main
