from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

from .sqlite_backend import SQLiteBackend


_MAX_UNISSUED_PER_DEVICE = 1000


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class KeyPackage:
    device_id: str
    kp_b64: str
    created_ms: int
    issued_ms: int | None
    revoked_ms: int | None


class KeyPackageStore:
    def publish(self, device_id: str, keypackages: List[str]) -> None:
        raise NotImplementedError

    def fetch(self, device_id: str, count: int) -> List[str]:
        raise NotImplementedError

    def rotate(self, device_id: str, revoke: bool, replacement: List[str]) -> None:
        raise NotImplementedError


class InMemoryKeyPackageStore(KeyPackageStore):
    def __init__(self, cap: int = _MAX_UNISSUED_PER_DEVICE) -> None:
        self._cap = cap
        self._store: dict[str, List[KeyPackage]] = {}

    def publish(self, device_id: str, keypackages: List[str]) -> None:
        if not keypackages:
            return
        now_ms = _now_ms()
        entries = self._store.setdefault(device_id, [])
        for kp in keypackages:
            entries.append(KeyPackage(device_id, kp, now_ms, None, None))
        self._enforce_cap(entries)

    def fetch(self, device_id: str, count: int) -> List[str]:
        entries = self._store.get(device_id, [])
        available = [kp for kp in entries if kp.issued_ms is None and kp.revoked_ms is None]
        to_issue = available[:count]
        issued_at = _now_ms()
        for kp in to_issue:
            kp.issued_ms = issued_at
        return [kp.kp_b64 for kp in to_issue]

    def rotate(self, device_id: str, revoke: bool, replacement: List[str]) -> None:
        entries = self._store.setdefault(device_id, [])
        if revoke:
            revoked_at = _now_ms()
            for kp in entries:
                if kp.issued_ms is None and kp.revoked_ms is None:
                    kp.revoked_ms = revoked_at
        if replacement:
            self.publish(device_id, replacement)

    def _enforce_cap(self, entries: List[KeyPackage]) -> None:
        if not entries:
            return
        unissued = [kp for kp in entries if kp.issued_ms is None and kp.revoked_ms is None]
        overflow = len(unissued) - self._cap
        if overflow <= 0:
            return
        remaining: List[KeyPackage] = []
        to_skip = overflow
        for kp in entries:
            if kp.issued_ms is None and kp.revoked_ms is None and to_skip > 0:
                to_skip -= 1
                continue
            remaining.append(kp)
        self._store[entries[0].device_id] = remaining if entries else []


class SQLiteKeyPackageStore(KeyPackageStore):
    def __init__(self, backend: SQLiteBackend, cap: int = _MAX_UNISSUED_PER_DEVICE) -> None:
        self._backend = backend
        self._cap = cap

    def publish(self, device_id: str, keypackages: List[str]) -> None:
        if not keypackages:
            return
        now_ms = _now_ms()
        with self._backend.lock:
            conn = self._backend.connection
            conn.execute("BEGIN IMMEDIATE")
            for kp in keypackages:
                conn.execute(
                    """
                    INSERT INTO keypackages (device_id, kp_b64, created_ms)
                    VALUES (?, ?, ?)
                    """,
                    (device_id, kp, now_ms),
                )
            self._enforce_cap(conn, device_id)
            conn.commit()

    def fetch(self, device_id: str, count: int) -> List[str]:
        if count <= 0:
            return []
        with self._backend.lock:
            conn = self._backend.connection
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT kp_id, kp_b64
                FROM keypackages
                WHERE device_id=? AND issued_ms IS NULL AND revoked_ms IS NULL
                ORDER BY kp_id ASC
                LIMIT ?
                """,
                (device_id, count),
            ).fetchall()
            kp_ids = [row[0] for row in rows]
            issued_at = _now_ms()
            if kp_ids:
                conn.executemany(
                    "UPDATE keypackages SET issued_ms=? WHERE kp_id=?",
                    [(issued_at, kp_id) for kp_id in kp_ids],
                )
            conn.commit()
        return [row[1] for row in rows]

    def rotate(self, device_id: str, revoke: bool, replacement: List[str]) -> None:
        now_ms = _now_ms()
        with self._backend.lock:
            conn = self._backend.connection
            conn.execute("BEGIN IMMEDIATE")
            if revoke:
                conn.execute(
                    """
                    UPDATE keypackages
                    SET revoked_ms=?
                    WHERE device_id=? AND issued_ms IS NULL AND revoked_ms IS NULL
                    """,
                    (now_ms, device_id),
                )
            if replacement:
                for kp in replacement:
                    conn.execute(
                        """
                        INSERT INTO keypackages (device_id, kp_b64, created_ms)
                        VALUES (?, ?, ?)
                        """,
                        (device_id, kp, now_ms),
                    )
                self._enforce_cap(conn, device_id)
            conn.commit()

    def _enforce_cap(self, conn, device_id: str) -> None:
        rows = conn.execute(
            """
            SELECT kp_id FROM keypackages
            WHERE device_id=? AND issued_ms IS NULL AND revoked_ms IS NULL
            ORDER BY kp_id ASC
            """,
            (device_id,),
        ).fetchall()
        overflow = len(rows) - self._cap
        if overflow <= 0:
            return
        to_delete = [row[0] for row in rows[:overflow]]
        conn.executemany("DELETE FROM keypackages WHERE kp_id=?", [(kp_id,) for kp_id in to_delete])
