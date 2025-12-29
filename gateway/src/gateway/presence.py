from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Set

from .sqlite_sessions import _now_ms


@dataclass
class PresenceConfig:
    max_ttl_seconds: int = 300
    min_ttl_seconds: int = 15
    max_watchlist_size: int = 256
    max_watchers_per_target: int = 256
    watch_mutations_per_min: int = 60
    renews_per_min: int = 60
    sweeper_interval_seconds: float = 1.0


@dataclass
class Lease:
    expires_at_ms: int
    invisible: bool
    last_seen_ms: int


class RateLimitExceeded(Exception):
    pass


class LimitExceeded(Exception):
    pass


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_ms: int = 60_000) -> None:
        self.limit = limit
        self.window_ms = window_ms
        self._windows: Dict[str, tuple[int, int]] = {}

    def allow(self, key: str, now_ms: int) -> bool:
        window_start, count = self._windows.get(key, (now_ms, 0))
        if now_ms - window_start >= self.window_ms:
            window_start, count = now_ms, 0
        count += 1
        self._windows[key] = (window_start, count)
        return count <= self.limit


class Presence:
    def __init__(self, config: PresenceConfig | None = None, *, now_func=_now_ms) -> None:
        self.config = config or PresenceConfig()
        self._now = now_func
        self._leases: Dict[str, Lease] = {}
        self._watchlists: Dict[str, Set[str]] = {}
        self._reverse_watchers: Dict[str, Set[str]] = {}
        self._callbacks: Dict[str, Callable[[dict], None]] = {}
        self._watch_rate = FixedWindowRateLimiter(self.config.watch_mutations_per_min)
        self._renew_rate = FixedWindowRateLimiter(self.config.renews_per_min)
        self._sweeper_task: asyncio.Task | None = None

    def start_sweeper(self) -> None:
        if self._sweeper_task is None:
            self._sweeper_task = asyncio.create_task(self._sweep())

    async def stop_sweeper(self) -> None:
        if self._sweeper_task is None:
            return
        self._sweeper_task.cancel()
        try:
            await self._sweeper_task
        except asyncio.CancelledError:
            pass
        self._sweeper_task = None

    async def _sweep(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.config.sweeper_interval_seconds)
                self.expire()
        except asyncio.CancelledError:
            return

    def _clamp_ttl(self, ttl_seconds: int) -> int:
        return max(self.config.min_ttl_seconds, min(self.config.max_ttl_seconds, ttl_seconds))

    def register_callback(self, device_id: str, callback: Callable[[dict], None]) -> None:
        self._callbacks[device_id] = callback

    def unregister_callback(self, device_id: str) -> None:
        self._callbacks.pop(device_id, None)

    def _bucket_last_seen(self, last_seen_ms: int) -> str:
        now_ms = self._now()
        delta_s = max(0, (now_ms - last_seen_ms) // 1000)
        if delta_s < 60:
            return "now"
        if delta_s < 5 * 60:
            return "5m"
        if delta_s < 60 * 60:
            return "1h"
        if delta_s < 24 * 60 * 60:
            return "1d"
        return "7d"

    def _eligible_watchers(self, target_device_id: str) -> Iterable[str]:
        target_watchlist = self._watchlists.get(target_device_id, set())
        watchers = self._reverse_watchers.get(target_device_id, set())
        for watcher in watchers:
            if watcher in target_watchlist:
                yield watcher

    def _notify(
        self,
        target_device_id: str,
        status: str,
        expires_at_ms: int,
        last_seen_ms: int,
        invisible: bool,
    ) -> None:
        if invisible:
            return
        frame = {
            "v": 1,
            "t": "presence.update",
            "body": {
                "user_id": target_device_id,
                "status": status,
                "expires_at": expires_at_ms,
                "last_seen_bucket": self._bucket_last_seen(last_seen_ms),
            },
        }
        for watcher in self._eligible_watchers(target_device_id):
            callback = self._callbacks.get(watcher)
            if callback is not None:
                callback(frame)

    def lease(self, device_id: str, ttl_seconds: int, *, invisible: bool = False) -> int:
        now_ms = self._now()
        if not self._renew_rate.allow(device_id, now_ms):
            raise RateLimitExceeded("presence renewals exceeded")

        ttl_ms = self._clamp_ttl(ttl_seconds) * 1000
        expires_at_ms = now_ms + ttl_ms
        prior = self._leases.get(device_id)
        was_visible = prior is not None and prior.expires_at_ms > now_ms and not prior.invisible

        self._leases[device_id] = Lease(expires_at_ms=expires_at_ms, invisible=invisible, last_seen_ms=now_ms)

        now_visible = expires_at_ms > now_ms and not invisible
        if now_visible and not was_visible:
            self._notify(device_id, "online", expires_at_ms, now_ms, invisible)
        if was_visible and invisible:
            self._notify(device_id, "offline", expires_at_ms, prior.last_seen_ms, prior.invisible)
        return expires_at_ms

    def renew(self, device_id: str, ttl_seconds: int, *, invisible: bool | None = None) -> int:
        now_ms = self._now()
        if not self._renew_rate.allow(device_id, now_ms):
            raise RateLimitExceeded("presence renewals exceeded")

        prior = self._leases.get(device_id)
        current_invisible = prior.invisible if prior else False
        new_invisible = current_invisible if invisible is None else invisible

        ttl_ms = self._clamp_ttl(ttl_seconds) * 1000
        expires_at_ms = now_ms + ttl_ms
        was_visible = prior is not None and prior.expires_at_ms > now_ms and not prior.invisible

        self._leases[device_id] = Lease(expires_at_ms=expires_at_ms, invisible=new_invisible, last_seen_ms=now_ms)

        now_visible = expires_at_ms > now_ms and not new_invisible
        if now_visible and not was_visible:
            self._notify(device_id, "online", expires_at_ms, now_ms, new_invisible)
        if was_visible and new_invisible:
            self._notify(device_id, "offline", expires_at_ms, prior.last_seen_ms, prior.invisible)
        return expires_at_ms

    def expire(self) -> None:
        now_ms = self._now()
        expired: list[tuple[str, Lease]] = []
        for device_id, lease in list(self._leases.items()):
            if lease.expires_at_ms <= now_ms:
                expired.append((device_id, lease))
                self._leases.pop(device_id, None)

        for device_id, lease in expired:
            self._notify(device_id, "offline", lease.expires_at_ms, lease.last_seen_ms, lease.invisible)

    def watch(self, watcher_device_id: str, contacts: Iterable[str]) -> None:
        now_ms = self._now()
        if not self._watch_rate.allow(watcher_device_id, now_ms):
            raise RateLimitExceeded("watch mutations exceeded")
        contacts_set = {c for c in contacts if isinstance(c, str)}
        watchlist = self._watchlists.get(watcher_device_id, set())
        new_total = len(watchlist | contacts_set)
        if new_total > self.config.max_watchlist_size:
            raise LimitExceeded("watchlist too large")

        for target in contacts_set:
            if target in watchlist:
                continue
            watchers = self._reverse_watchers.get(target, set())
            if len(watchers) >= self.config.max_watchers_per_target:
                raise LimitExceeded("target watcher cap reached")

        for target in contacts_set:
            if target in watchlist:
                continue
            watchlist.add(target)
            watchers = self._reverse_watchers.setdefault(target, set())
            watchers.add(watcher_device_id)
        self._watchlists[watcher_device_id] = watchlist

    def unwatch(self, watcher_device_id: str, contacts: Iterable[str]) -> None:
        now_ms = self._now()
        if not self._watch_rate.allow(watcher_device_id, now_ms):
            raise RateLimitExceeded("watch mutations exceeded")
        contacts_set = {c for c in contacts if isinstance(c, str)}
        watchlist = self._watchlists.get(watcher_device_id, set())
        for target in contacts_set:
            if target in watchlist:
                watchlist.remove(target)
                watchers = self._reverse_watchers.get(target)
                if watchers:
                    watchers.discard(watcher_device_id)
                    if not watchers:
                        self._reverse_watchers.pop(target, None)
        if watchlist:
            self._watchlists[watcher_device_id] = watchlist
        elif watcher_device_id in self._watchlists:
            self._watchlists.pop(watcher_device_id, None)

    def watchlist_size(self, watcher_device_id: str) -> int:
        return len(self._watchlists.get(watcher_device_id, set()))

