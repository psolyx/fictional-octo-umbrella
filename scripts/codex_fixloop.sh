#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="/tmp/pr-check.log"

cd "$(git rev-parse --show-toplevel)"

{
  echo "==> Running make check";
  make check;
} |& tee "$LOG_FILE"
