#!/usr/bin/env bash
set -euo pipefail

env PYTHONPATH=clients/cli/src python -m cli_app.phase5_2_signoff_verify_report_main
