from __future__ import annotations

from typing import Dict, Tuple


class CursorStore:
    """Tracks per-device acknowledgement cursors per conversation."""

    def __init__(self) -> None:
        self._positions: Dict[Tuple[str, str], int] = {}

    def ack(self, device_id: str, conv_id: str, seq: int) -> int:
        """Advance the acknowledgement cursor to the next sequence to deliver."""

        if seq < 0:
            raise ValueError("ack cursor must be non-negative")
        return self._set_next_seq(device_id, conv_id, seq + 1)

    def advance(self, device_id: str, conv_id: str, next_seq: int) -> int:
        """Persist the next sequence to deliver, keeping monotonicity."""

        if next_seq < 1:
            raise ValueError("next_seq must be positive")
        return self._set_next_seq(device_id, conv_id, next_seq)

    def last_ack(self, device_id: str, conv_id: str) -> int:
        """Return the next sequence to deliver for the device/conversation."""

        return self.next_seq(device_id, conv_id)

    def next_seq(self, device_id: str, conv_id: str) -> int:
        """Return the next sequence to deliver for the device/conversation."""

        return self._positions.get((device_id, conv_id), 1)

    def _set_next_seq(self, device_id: str, conv_id: str, candidate: int) -> int:
        key = (device_id, conv_id)
        current = self._positions.get(key, 1)
        next_seq = max(current, candidate)
        self._positions[key] = next_seq
        return next_seq
