"""Redaction helpers for safe TUI diagnostics."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = {
    "auth_token",
    "bootstrap_token",
    "device_credential",
    "session_token",
    "resume_token",
    "token",
    "credential",
}

_KEY_VALUE_RE = re.compile(
    r"([\"']?(?:auth_token|bootstrap_token|device_credential|session_token|resume_token|token|credential)[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}&]+)",
    flags=re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(Bearer\s+)([^\s]+)", flags=re.IGNORECASE)
_QUERY_RE = re.compile(r"([?&](?:auth_token|resume_token|token|credential)=)([^&#\s]+)", flags=re.IGNORECASE)


def redact_text(text: str) -> str:
    """Redact secret-bearing token fragments from unstructured text."""

    rendered = str(text)
    rendered = _BEARER_RE.sub(r"\1[REDACTED]", rendered)
    rendered = _KEY_VALUE_RE.sub(r"\1[REDACTED]", rendered)
    rendered = _QUERY_RE.sub(r"\1[REDACTED]", rendered)
    return rendered


def redact_mapping(obj: dict[str, Any]) -> dict[str, Any]:
    """Deep redact mapping values for known sensitive keys."""

    redacted: dict[str, Any] = {}
    for key, value in obj.items():
        lower_key = str(key).lower()
        if lower_key in SENSITIVE_KEYS:
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [redact_mapping(item) if isinstance(item, dict) else item for item in value]
        else:
            redacted[key] = value
    return redacted
