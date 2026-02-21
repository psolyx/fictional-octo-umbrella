"""Compatibility wrapper for `python -m unittest gateway.tests.test_docs_retention_and_idempotency`."""

from __future__ import annotations

from pathlib import Path
import runpy

_TEST_FILE = Path(__file__).resolve().parents[3] / "tests" / "test_docs_retention_and_idempotency.py"
globals().update(runpy.run_path(str(_TEST_FILE)))
