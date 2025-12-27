from __future__ import annotations

from typing import Dict, Tuple


class CursorStore:
    """Tracks per-device acknowledgement cursors per conversation."""

    def __init__(self) -> None:
        self._positions: Dict[Tuple[str, str], int] = {}

    def ack(self, device_id: str, conv_id: str, acked_seq: int) -> int:
        """Advance the acknowledgement cursor while preserving monotonicity."""

        if acked_seq < 0:
            raise ValueError("acked_seq must be non-negative")

        key = (device_id, conv_id)
        current_next = self._positions.get(key, 1)
        next_seq = max(current_next, acked_seq + 1)
        self._positions[key] = next_seq
        return next_seq

    def next_seq(self, device_id: str, conv_id: str) -> int:
        """Return the next sequence number to deliver for the device/conversation."""

        return self._positions.get((device_id, conv_id), 1)

    def last_ack(self, device_id: str, conv_id: str) -> int:
        """Return the last acknowledged sequence for the device/conversation."""

        return self.next_seq(device_id, conv_id) - 1
