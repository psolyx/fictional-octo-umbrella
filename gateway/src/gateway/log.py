from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ConversationEvent:
    """An immutable log event emitted by the gateway core."""

    conv_id: str
    seq: int
    msg_id: str
    envelope_b64: str
    sender_device_id: str
    ts_ms: int


class ConversationLog:
    """In-memory, append-only conversation log with idempotency enforcement."""

    def __init__(self) -> None:
        self._events: Dict[str, List[ConversationEvent]] = {}
        self._idempotency: Dict[Tuple[str, str], ConversationEvent] = {}

    def append(
        self,
        conv_id: str,
        msg_id: str,
        envelope_bytes_or_b64: bytes | str,
        sender_device_id: str,
        ts_ms: int,
    ) -> tuple[int, ConversationEvent, bool]:
        """Append a new event or return the existing one for the idempotency key.

        Sequence numbers are monotonic per conversation starting at 1. The
        original event is returned when the same ``(conv_id, msg_id)`` is
        appended multiple times.

        Returns
        -------
        tuple
            (seq, event, created) where ``created`` indicates whether a new
            event was inserted (``True``) or an existing idempotent event was
            returned (``False``).
        """

        key = (conv_id, msg_id)
        if key in self._idempotency:
            event = self._idempotency[key]
            return event.seq, event, False

        envelope_b64 = self._to_b64(envelope_bytes_or_b64)
        seq = len(self._events.get(conv_id, [])) + 1
        event = ConversationEvent(
            conv_id=conv_id,
            seq=seq,
            msg_id=msg_id,
            envelope_b64=envelope_b64,
            sender_device_id=sender_device_id,
            ts_ms=ts_ms,
        )

        self._events.setdefault(conv_id, []).append(event)
        self._idempotency[key] = event
        return seq, event, True

    def list_since(self, conv_id: str, after_seq: int, limit: int | None = None) -> list[ConversationEvent]:
        """Return events for ``conv_id`` with ``seq`` greater than ``after_seq``.

        Results are ordered by ascending ``seq`` and constrained by ``limit``
        when provided.
        """

        if after_seq < 0:
            raise ValueError("after_seq must be non-negative")
        events = self._events.get(conv_id, [])
        start_index = after_seq
        slice_end = None if limit is None else start_index + max(limit, 0)
        return list(events[start_index:slice_end])

    def list_from(self, conv_id: str, from_seq: int, limit: int | None = None) -> list[ConversationEvent]:
        """Return events for ``conv_id`` with ``seq`` greater than or equal to ``from_seq``.

        Results are ordered by ascending ``seq`` and constrained by ``limit``
        when provided.
        """

        if from_seq < 1:
            raise ValueError("from_seq must be at least 1")

        events = self._events.get(conv_id, [])
        start_index = from_seq - 1
        slice_end = None if limit is None else start_index + max(limit, 0)
        return list(events[start_index:slice_end])

    def bounds(self, conv_id: str) -> tuple[int | None, int | None, int | None]:
        events = self._events.get(conv_id, [])
        if not events:
            return None, None, None
        earliest = events[0]
        latest = events[-1]
        return earliest.seq, latest.seq, latest.ts_ms

    def earliest_seq(self, conv_id: str) -> int | None:
        earliest_seq, _, _ = self.bounds(conv_id)
        return earliest_seq

    def latest_seq(self, conv_id: str) -> int | None:
        _, latest_seq, _ = self.bounds(conv_id)
        return latest_seq

    def latest_ts_ms(self, conv_id: str) -> int | None:
        _, _, latest_ts_ms = self.bounds(conv_id)
        return latest_ts_ms

    @staticmethod
    def _to_b64(envelope_bytes_or_b64: bytes | str) -> str:
        if isinstance(envelope_bytes_or_b64, bytes):
            return base64.b64encode(envelope_bytes_or_b64).decode("ascii")
        return envelope_bytes_or_b64
