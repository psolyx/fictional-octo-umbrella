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
    max_blocklist_size: int = 256
    block_mutations_per_min: int = 60
    renews_per_min: int = 60
    sweeper_interval_seconds: float = 1.0


@dataclass
class Lease:
    user_id: str
    expires_at_ms: int
    invisible: bool
    last_seen_ms: int


@dataclass
class UserStatus:
    status: str
    expires_at_ms: int
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
        self._blocklists: Dict[str, Set[str]] = {}
        self._reverse_watchers: Dict[str, Set[str]] = {}
        self._callbacks: Dict[str, Callable[[dict], None]] = {}
        self._device_users: Dict[str, str] = {}
        self._user_devices: Dict[str, Set[str]] = {}
        self._user_status: Dict[str, UserStatus] = {}
        self._watch_rate = FixedWindowRateLimiter(self.config.watch_mutations_per_min)
        self._block_rate = FixedWindowRateLimiter(self.config.block_mutations_per_min)
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

    def register_callback(self, user_id: str, device_id: str, callback: Callable[[dict], None]) -> None:
        self._callbacks[device_id] = callback
        self._device_users[device_id] = user_id
        devices = self._user_devices.setdefault(user_id, set())
        devices.add(device_id)

    def unregister_callback(self, device_id: str) -> None:
        self._callbacks.pop(device_id, None)
        user_id = self._device_users.pop(device_id, None)
        if user_id is not None:
            devices = self._user_devices.get(user_id)
            if devices is not None:
                devices.discard(device_id)
                if not devices:
                    self._user_devices.pop(user_id, None)

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

    def _eligible_watchers(self, target_user_id: str) -> Iterable[str]:
        target_watchlist = self._watchlists.get(target_user_id, set())
        watchers = self._reverse_watchers.get(target_user_id, set())
        for watcher in watchers:
            if self._can_view_status(watcher, target_user_id, target_watchlist=target_watchlist):
                yield watcher

    def _can_view_status(self, viewer_user_id: str, target_user_id: str, *, target_watchlist: Set[str] | None = None) -> bool:
        if not viewer_user_id or not target_user_id or viewer_user_id == target_user_id:
            return False
        if self.is_blocked(viewer_user_id, target_user_id):
            return False
        viewer_watchlist = self._watchlists.get(viewer_user_id, set())
        if target_user_id not in viewer_watchlist:
            return False
        active_target_watchlist = target_watchlist if target_watchlist is not None else self._watchlists.get(target_user_id, set())
        return viewer_user_id in active_target_watchlist

    def _fanout(self, watcher_user_id: str, frame: dict) -> None:
        for device_id in self._user_devices.get(watcher_user_id, set()):
            callback = self._callbacks.get(device_id)
            if callback is not None:
                callback(frame)

    def _notify(
        self,
        target_user_id: str,
        status: str,
        expires_at_ms: int,
        last_seen_ms: int,
    ) -> None:
        frame = {
            "v": 1,
            "t": "presence.update",
            "body": {
                "user_id": target_user_id,
                "status": status,
                "expires_at": expires_at_ms,
                "last_seen_bucket": self._bucket_last_seen(last_seen_ms),
            },
        }
        for watcher in self._eligible_watchers(target_user_id):
            self._fanout(watcher, frame)

    def _compute_user_status(self, user_id: str, previous: UserStatus | None) -> UserStatus:
        now_ms = self._now()
        leases = [lease for lease in self._leases.values() if lease.user_id == user_id]
        visible = [lease for lease in leases if lease.expires_at_ms > now_ms and not lease.invisible]
        if visible:
            expires_at_ms = max(lease.expires_at_ms for lease in visible)
            last_seen_ms = max(lease.last_seen_ms for lease in visible)
            return UserStatus("online", expires_at_ms, last_seen_ms)

        expires_at_ms = previous.expires_at_ms if previous and previous.status == "online" else max(
            (lease.expires_at_ms for lease in leases), default=now_ms
        )
        last_seen_ms = previous.last_seen_ms if previous else max((lease.last_seen_ms for lease in leases), default=now_ms)
        return UserStatus("offline", expires_at_ms, last_seen_ms)

    def _update_user_status(self, user_id: str) -> None:
        previous = self._user_status.get(user_id)
        current = self._compute_user_status(user_id, previous)
        should_notify = False
        if previous is None:
            should_notify = current.status == "online"
        elif current.status != previous.status:
            should_notify = True
        elif current.status == "online" and current.expires_at_ms != previous.expires_at_ms:
            should_notify = True
        if should_notify:
            self._notify(user_id, current.status, current.expires_at_ms, current.last_seen_ms)
        if current.status == "offline" and not any(lease.user_id == user_id for lease in self._leases.values()):
            self._user_status.pop(user_id, None)
        else:
            self._user_status[user_id] = current

    def lease(self, user_id: str, device_id: str, ttl_seconds: int, *, invisible: bool = False) -> int:
        now_ms = self._now()
        if not self._renew_rate.allow(device_id, now_ms):
            raise RateLimitExceeded("presence renewals exceeded")

        ttl_ms = self._clamp_ttl(ttl_seconds) * 1000
        expires_at_ms = now_ms + ttl_ms
        self._leases[device_id] = Lease(
            user_id=user_id, expires_at_ms=expires_at_ms, invisible=invisible, last_seen_ms=now_ms
        )

        self._update_user_status(user_id)
        return expires_at_ms

    def renew(self, user_id: str, device_id: str, ttl_seconds: int, *, invisible: bool | None = None) -> int:
        now_ms = self._now()
        if not self._renew_rate.allow(device_id, now_ms):
            raise RateLimitExceeded("presence renewals exceeded")

        prior = self._leases.get(device_id)
        current_invisible = prior.invisible if prior else False
        new_invisible = current_invisible if invisible is None else invisible

        ttl_ms = self._clamp_ttl(ttl_seconds) * 1000
        expires_at_ms = now_ms + ttl_ms
        self._leases[device_id] = Lease(
            user_id=user_id, expires_at_ms=expires_at_ms, invisible=new_invisible, last_seen_ms=now_ms
        )

        self._update_user_status(user_id)
        return expires_at_ms

    def expire(self) -> None:
        now_ms = self._now()
        expired: list[tuple[str, Lease]] = []
        for device_id, lease in list(self._leases.items()):
            if lease.expires_at_ms <= now_ms:
                expired.append((device_id, lease))
                self._leases.pop(device_id, None)

        for device_id, lease in expired:
            self._update_user_status(lease.user_id)

    def watch(self, watcher_user_id: str, contacts: Iterable[str]) -> None:
        now_ms = self._now()
        if not self._watch_rate.allow(watcher_user_id, now_ms):
            raise RateLimitExceeded("watch mutations exceeded")
        contacts_set = {c for c in contacts if isinstance(c, str) and not self.is_blocked(watcher_user_id, c)}
        watchlist = self._watchlists.get(watcher_user_id, set())
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
            watchers.add(watcher_user_id)
        self._watchlists[watcher_user_id] = watchlist

    def unwatch(self, watcher_user_id: str, contacts: Iterable[str]) -> None:
        now_ms = self._now()
        if not self._watch_rate.allow(watcher_user_id, now_ms):
            raise RateLimitExceeded("watch mutations exceeded")
        contacts_set = {c for c in contacts if isinstance(c, str)}
        watchlist = self._watchlists.get(watcher_user_id, set())
        for target in contacts_set:
            if target in watchlist:
                watchlist.remove(target)
                watchers = self._reverse_watchers.get(target)
                if watchers:
                    watchers.discard(watcher_user_id)
                    if not watchers:
                        self._reverse_watchers.pop(target, None)
        if watchlist:
            self._watchlists[watcher_user_id] = watchlist
        elif watcher_user_id in self._watchlists:
            self._watchlists.pop(watcher_user_id, None)

    def watchlist_size(self, watcher_user_id: str) -> int:
        return len(self._watchlists.get(watcher_user_id, set()))

    def block(self, blocker_user_id: str, targets: Iterable[str]) -> None:
        now_ms = self._now()
        if not self._block_rate.allow(blocker_user_id, now_ms):
            raise RateLimitExceeded("block mutations exceeded")

        targets_set = {t for t in targets if isinstance(t, str)}
        blocklist = self._blocklists.get(blocker_user_id, set())
        new_total = len(blocklist | targets_set)
        if new_total > self.config.max_blocklist_size:
            raise LimitExceeded("blocklist too large")

        if targets_set:
            blocklist |= targets_set
            self._blocklists[blocker_user_id] = blocklist

    def unblock(self, blocker_user_id: str, targets: Iterable[str]) -> None:
        now_ms = self._now()
        if not self._block_rate.allow(blocker_user_id, now_ms):
            raise RateLimitExceeded("block mutations exceeded")

        targets_set = {t for t in targets if isinstance(t, str)}
        blocklist = self._blocklists.get(blocker_user_id, set())
        for target in targets_set:
            blocklist.discard(target)

        if blocklist:
            self._blocklists[blocker_user_id] = blocklist
        elif blocker_user_id in self._blocklists:
            self._blocklists.pop(blocker_user_id, None)

    def is_blocked(self, user_a: str, user_b: str) -> bool:
        if user_a == user_b:
            return False
        return user_b in self._blocklists.get(user_a, set()) or user_a in self._blocklists.get(user_b, set())

    def status_for_viewer(self, viewer_user_id: str, contacts: Iterable[str]) -> list[dict]:
        statuses: list[dict] = []
        for user_id in sorted({contact for contact in contacts if isinstance(contact, str)}):
            entry = {
                "user_id": user_id,
                "status": "unavailable",
                "expires_at": self._now(),
                "last_seen_bucket": "7d",
            }
            if self._can_view_status(viewer_user_id, user_id):
                user_status = self._user_status.get(user_id)
                if user_status is None:
                    user_status = self._compute_user_status(user_id, previous=None)
                entry["status"] = user_status.status
                entry["expires_at"] = user_status.expires_at_ms
                entry["last_seen_bucket"] = self._bucket_last_seen(user_status.last_seen_ms)
            statuses.append(entry)
        return statuses

    def blocklist_size(self, user_id: str) -> int:
        return len(self._blocklists.get(user_id, set()))
