from __future__ import annotations

from typing import Dict, Tuple


class CursorStore:
    """Tracks per-device acknowledgement cursors per conversation."""

    def __init__(self) -> None:
        self._positions: Dict[Tuple[str, str], int] = {}

    def ack(self, device_id: str, conv_id: str, seq: int) -> int:
        """Advance the acknowledgement cursor; rejects regressions."""

        key = (device_id, conv_id)
        current = self._positions.get(key, 0)
        if seq < current:
            raise ValueError("ack cursor must be monotonic")
        self._positions[key] = seq
        return seq

    def last_ack(self, device_id: str, conv_id: str) -> int:
        """Return the last acknowledged sequence for the device/conversation."""

        return self._positions.get((device_id, conv_id), 0)
