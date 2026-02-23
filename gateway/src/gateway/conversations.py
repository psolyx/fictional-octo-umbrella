from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

from .presence import FixedWindowRateLimiter, LimitExceeded, RateLimitExceeded
from .sqlite_backend import SQLiteBackend
from .sqlite_sessions import _now_ms


MAX_MEMBERS_PER_CONV = 1024
INVITES_PER_MIN = 60
REMOVES_PER_MIN = 60
MAX_INLINE_MEMBERS = 20
ROLE_RANK = {"owner": 0, "admin": 1, "member": 2}


@dataclass
class Conversation:
    conv_id: str
    owner_user_id: str
    created_at_ms: int
    home_gateway: str = ""


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._conversations: Dict[str, Conversation] = {}
        self._members: Dict[str, Dict[str, str]] = {}
        self._invite_limits = FixedWindowRateLimiter(INVITES_PER_MIN)
        self._remove_limits = FixedWindowRateLimiter(REMOVES_PER_MIN)

    def create(self, conv_id: str, owner_user_id: str, members: Iterable[str], *, home_gateway: str) -> None:
        if conv_id in self._conversations:
            raise ValueError("conversation already exists")
        member_set = set(members)
        member_set.add(owner_user_id)
        if len(member_set) > MAX_MEMBERS_PER_CONV:
            raise LimitExceeded("too many members")
        conversation = Conversation(
            conv_id=conv_id,
            owner_user_id=owner_user_id,
            created_at_ms=_now_ms(),
            home_gateway=home_gateway,
        )
        self._conversations[conv_id] = conversation
        roster = {user_id: "member" for user_id in member_set}
        roster[owner_user_id] = "owner"
        self._members[conv_id] = roster

    def invite(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_admin(conversation, actor_user_id)
        now_ms = _now_ms()
        if not self._invite_limits.allow(f"{conv_id}:{actor_user_id}", now_ms):
            raise RateLimitExceeded("invite rate limit exceeded")
        roster = self._members.setdefault(conv_id, {})
        new_members = set(members) - set(roster.keys())
        if len(roster) + len(new_members) > MAX_MEMBERS_PER_CONV:
            raise LimitExceeded("too many members")
        for user_id in new_members:
            roster[user_id] = "member"

    def remove(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_admin(conversation, actor_user_id)
        now_ms = _now_ms()
        if not self._remove_limits.allow(f"{conv_id}:{actor_user_id}", now_ms):
            raise RateLimitExceeded("remove rate limit exceeded")
        roster = self._members.setdefault(conv_id, {})
        for user_id in members:
            if user_id == conversation.owner_user_id:
                continue
            roster.pop(user_id, None)

    def promote_admin(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_owner(conversation, actor_user_id)
        roster = self._members.setdefault(conv_id, {})
        for user_id in members:
            if user_id == conversation.owner_user_id:
                continue
            if user_id in roster:
                roster[user_id] = "admin"

    def demote_admin(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_owner(conversation, actor_user_id)
        roster = self._members.setdefault(conv_id, {})
        for user_id in members:
            if user_id == conversation.owner_user_id:
                continue
            if roster.get(user_id) == "admin":
                roster[user_id] = "member"

    def is_member(self, conv_id: str, user_id: str) -> bool:
        roster = self._members.get(conv_id)
        if roster is None:
            return False
        return user_id in roster

    def role(self, conv_id: str, user_id: str) -> str | None:
        roster = self._members.get(conv_id)
        if roster is None:
            return None
        return roster.get(user_id)

    def home_gateway(self, conv_id: str, default_gateway: str) -> str:
        conversation = self._conversations.get(conv_id)
        if conversation is None:
            raise ValueError("unknown conversation")
        if not conversation.home_gateway:
            conversation.home_gateway = default_gateway
        return conversation.home_gateway

    def is_known(self, conv_id: str) -> bool:
        return conv_id in self._conversations

    def list_for_user(self, user_id: str) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for conv_id, conversation in self._conversations.items():
            roster = self._members.get(conv_id, {})
            role = roster.get(user_id)
            if role is None:
                continue
            item: dict[str, object] = {
                "conv_id": conv_id,
                "role": role,
                "created_at_ms": conversation.created_at_ms,
                "home_gateway": conversation.home_gateway,
                "member_count": len(roster),
            }
            if len(roster) <= MAX_INLINE_MEMBERS:
                item["members"] = sorted(roster.keys())
            items.append(item)
        items.sort(key=lambda row: (int(row["created_at_ms"]), str(row["conv_id"])))
        return items

    def list_members(self, conv_id: str) -> list[dict[str, str]]:
        conversation = self._require_conversation(conv_id)
        roster = self._members.get(conversation.conv_id, {})
        members = [
            {"user_id": user_id, "role": role}
            for user_id, role in roster.items()
        ]
        members.sort(key=lambda item: (ROLE_RANK.get(item["role"], 999), item["user_id"]))
        return members

    def _require_conversation(self, conv_id: str) -> Conversation:
        conversation = self._conversations.get(conv_id)
        if conversation is None:
            raise ValueError("unknown conversation")
        return conversation

    def _require_admin(self, conversation: Conversation, actor_user_id: str) -> None:
        role = self.role(conversation.conv_id, actor_user_id)
        if role not in ("owner", "admin"):
            raise PermissionError("forbidden")

    def _require_owner(self, conversation: Conversation, actor_user_id: str) -> None:
        if conversation.owner_user_id != actor_user_id:
            raise PermissionError("forbidden")


class SQLiteConversationStore:
    def __init__(self, backend: SQLiteBackend) -> None:
        self._backend = backend
        self._invite_limits = FixedWindowRateLimiter(INVITES_PER_MIN)
        self._remove_limits = FixedWindowRateLimiter(REMOVES_PER_MIN)

    def create(self, conv_id: str, owner_user_id: str, members: Iterable[str], *, home_gateway: str) -> None:
        member_set = set(members)
        member_set.add(owner_user_id)
        if len(member_set) > MAX_MEMBERS_PER_CONV:
            raise LimitExceeded("too many members")
        now_ms = _now_ms()
        with self._backend.lock:
            conn = self._backend.connection
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                existing = cursor.execute(
                    "SELECT conv_id FROM conversations WHERE conv_id=?", (conv_id,)
                ).fetchone()
                if existing:
                    conn.rollback()
                    raise ValueError("conversation already exists")
                cursor.execute(
                    "INSERT INTO conversations (conv_id, owner_user_id, created_at_ms, home_gateway) VALUES (?, ?, ?, ?)",
                    (conv_id, owner_user_id, now_ms, home_gateway),
                )
                for member in member_set:
                    role = "owner" if member == owner_user_id else "member"
                    cursor.execute(
                        "INSERT INTO conversation_members (conv_id, user_id, role) VALUES (?, ?, ?)",
                        (conv_id, member, role),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def invite(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_admin(conversation, actor_user_id)
        now_ms = _now_ms()
        if not self._invite_limits.allow(f"{conv_id}:{actor_user_id}", now_ms):
            raise RateLimitExceeded("invite rate limit exceeded")
        with self._backend.lock:
            conn = self._backend.connection
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                existing_members = {
                    row[0]
                    for row in cursor.execute(
                        "SELECT user_id FROM conversation_members WHERE conv_id=?", (conv_id,)
                    ).fetchall()
                }
                new_members = set(members) - existing_members
                if len(existing_members) + len(new_members) > MAX_MEMBERS_PER_CONV:
                    conn.rollback()
                    raise LimitExceeded("too many members")
                for member in new_members:
                    cursor.execute(
                        "INSERT OR IGNORE INTO conversation_members (conv_id, user_id, role) VALUES (?, ?, ?)",
                        (conv_id, member, "member"),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def remove(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_admin(conversation, actor_user_id)
        now_ms = _now_ms()
        if not self._remove_limits.allow(f"{conv_id}:{actor_user_id}", now_ms):
            raise RateLimitExceeded("remove rate limit exceeded")
        with self._backend.lock:
            conn = self._backend.connection
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                for member in members:
                    if member == conversation.owner_user_id:
                        continue
                    cursor.execute(
                        "DELETE FROM conversation_members WHERE conv_id=? AND user_id=?",
                        (conv_id, member),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def promote_admin(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_owner(conversation, actor_user_id)
        with self._backend.lock:
            conn = self._backend.connection
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                for member in members:
                    if member == conversation.owner_user_id:
                        continue
                    cursor.execute(
                        "UPDATE conversation_members SET role='admin' WHERE conv_id=? AND user_id=?",
                        (conv_id, member),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def demote_admin(self, conv_id: str, actor_user_id: str, members: Iterable[str]) -> None:
        conversation = self._require_conversation(conv_id)
        self._require_owner(conversation, actor_user_id)
        with self._backend.lock:
            conn = self._backend.connection
            cursor = conn.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                for member in members:
                    if member == conversation.owner_user_id:
                        continue
                    cursor.execute(
                        "UPDATE conversation_members SET role='member' WHERE conv_id=? AND user_id=? AND role='admin'",
                        (conv_id, member),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def is_member(self, conv_id: str, user_id: str) -> bool:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT 1 FROM conversation_members WHERE conv_id=? AND user_id=?",
                (conv_id, user_id),
            ).fetchone()
        return row is not None

    def is_known(self, conv_id: str) -> bool:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT 1 FROM conversations WHERE conv_id=?",
                (conv_id,),
            ).fetchone()
        return row is not None

    def role(self, conv_id: str, user_id: str) -> str | None:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT role FROM conversation_members WHERE conv_id=? AND user_id=?",
                (conv_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return row[0]

    def home_gateway(self, conv_id: str, default_gateway: str) -> str:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT home_gateway FROM conversations WHERE conv_id=?",
                (conv_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown conversation")
            home_gateway = row[0] or default_gateway
            if not row[0] and default_gateway:
                self._backend.connection.execute(
                    "UPDATE conversations SET home_gateway=? WHERE conv_id=?",
                    (home_gateway, conv_id),
                )
        return home_gateway

    def list_for_user(self, user_id: str) -> list[dict[str, object]]:
        with self._backend.lock:
            rows = self._backend.connection.execute(
                """
                SELECT
                    c.conv_id,
                    c.created_at_ms,
                    c.home_gateway,
                    cm.role,
                    (
                        SELECT COUNT(*)
                        FROM conversation_members cm_count
                        WHERE cm_count.conv_id = c.conv_id
                    ) AS member_count
                FROM conversations c
                JOIN conversation_members cm ON cm.conv_id = c.conv_id
                WHERE cm.user_id = ?
                ORDER BY c.created_at_ms ASC, c.conv_id ASC
                """,
                (user_id,),
            ).fetchall()
            members_by_conv: dict[str, list[str]] = {}
            small_conv_ids = [
                str(row["conv_id"])
                for row in rows
                if int(row["member_count"]) <= MAX_INLINE_MEMBERS
            ]
            if small_conv_ids:
                placeholders = ",".join("?" for _ in small_conv_ids)
                member_rows = self._backend.connection.execute(
                    f"""
                    SELECT conv_id, user_id
                    FROM conversation_members
                    WHERE conv_id IN ({placeholders})
                    ORDER BY conv_id ASC, user_id ASC
                    """,
                    tuple(small_conv_ids),
                ).fetchall()
                for member_row in member_rows:
                    conv_id = str(member_row["conv_id"])
                    members_by_conv.setdefault(conv_id, []).append(str(member_row["user_id"]))

        items: list[dict[str, object]] = []
        for row in rows:
            conv_id = str(row["conv_id"])
            item: dict[str, object] = {
                "conv_id": conv_id,
                "role": str(row["role"]),
                "created_at_ms": int(row["created_at_ms"]),
                "home_gateway": str(row["home_gateway"]),
                "member_count": int(row["member_count"]),
            }
            members = members_by_conv.get(conv_id)
            if members is not None:
                item["members"] = members
            items.append(item)
        return items

    def list_members(self, conv_id: str) -> list[dict[str, str]]:
        with self._backend.lock:
            known = self._backend.connection.execute(
                "SELECT 1 FROM conversations WHERE conv_id=?",
                (conv_id,),
            ).fetchone()
            if known is None:
                raise ValueError("unknown conversation")
            rows = self._backend.connection.execute(
                "SELECT user_id, role FROM conversation_members WHERE conv_id=?",
                (conv_id,),
            ).fetchall()
        members = [
            {"user_id": str(row["user_id"]), "role": str(row["role"])}
            for row in rows
        ]
        members.sort(key=lambda item: (ROLE_RANK.get(item["role"], 999), item["user_id"]))
        return members

    def _require_conversation(self, conv_id: str) -> Conversation:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT conv_id, owner_user_id, created_at_ms, home_gateway FROM conversations WHERE conv_id=?",
                (conv_id,),
            ).fetchone()
        if row is None:
            raise ValueError("unknown conversation")
        return Conversation(conv_id=row[0], owner_user_id=row[1], created_at_ms=row[2], home_gateway=row[3])

    def _require_admin(self, conversation: Conversation, actor_user_id: str) -> None:
        role = self.role(conversation.conv_id, actor_user_id)
        if role not in ("owner", "admin"):
            raise PermissionError("forbidden")

    def _require_owner(self, conversation: Conversation, actor_user_id: str) -> None:
        if conversation.owner_user_id != actor_user_id:
            raise PermissionError("forbidden")
