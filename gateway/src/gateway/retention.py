from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionPolicy:
    max_events_per_conv: int
    max_age_s: int
    sweep_interval_s: int
    cursor_stale_after_s: int
    hard_limits: bool

    @property
    def enabled(self) -> bool:
        return self.max_events_per_conv > 0 or self.max_age_s > 0

    @property
    def max_age_ms(self) -> int:
        return max(self.max_age_s, 0) * 1000

    @property
    def cursor_stale_after_ms(self) -> int:
        return max(self.cursor_stale_after_s, 0) * 1000


@dataclass(frozen=True)
class ReplayWindowExceeded(Exception):
    conv_id: str
    requested_from_seq: int
    earliest_seq: int
    latest_seq: int


def _parse_non_negative_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _parse_bool01(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    if raw not in {"0", "1"}:
        raise ValueError(f"{name} must be 0 or 1")
    return raw == "1"


def load_retention_policy_from_env() -> RetentionPolicy:
    max_events = _parse_non_negative_int("GATEWAY_RETENTION_MAX_EVENTS_PER_CONV", 0)
    max_age_s = _parse_non_negative_int("GATEWAY_RETENTION_MAX_AGE_S", 0)
    sweep_interval_s = _parse_non_negative_int("GATEWAY_RETENTION_SWEEP_INTERVAL_S", 60)
    cursor_stale_after_s = _parse_non_negative_int("GATEWAY_CURSOR_STALE_AFTER_S", 0)
    hard_limits = _parse_bool01("GATEWAY_RETENTION_HARD_LIMITS", False)
    return RetentionPolicy(
        max_events_per_conv=max_events,
        max_age_s=max_age_s,
        sweep_interval_s=max(1, sweep_interval_s),
        cursor_stale_after_s=cursor_stale_after_s,
        hard_limits=hard_limits,
    )
