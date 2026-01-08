"""Opaque DM envelope helpers."""

from __future__ import annotations

import base64
import binascii


class EnvelopeError(ValueError):
    """Raised when an envelope cannot be parsed or constructed."""


def pack(kind: int, payload_b64: str) -> str:
    if not isinstance(kind, int) or not (0 <= kind <= 255):
        raise EnvelopeError("kind must be an int between 0 and 255")
    try:
        payload_bytes = base64.b64decode(payload_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EnvelopeError("payload_b64 must be valid base64") from exc
    env_bytes = bytes([kind]) + payload_bytes
    return base64.b64encode(env_bytes).decode("utf-8")


def unpack(env_b64: str) -> tuple[int, str]:
    try:
        env_bytes = base64.b64decode(env_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EnvelopeError("env_b64 must be valid base64") from exc
    if not env_bytes:
        raise EnvelopeError("env_b64 must contain at least one byte")
    kind = env_bytes[0]
    payload_b64 = base64.b64encode(env_bytes[1:]).decode("utf-8")
    return kind, payload_b64
