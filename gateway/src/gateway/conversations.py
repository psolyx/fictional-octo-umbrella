from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

from .presence import FixedWindowRateLimiter, LimitExceeded, RateLimitExceeded
from .sqlite_backend import SQLiteBackend
from .sqlite_sessions import _now_ms


MAX_MEMBERS_PER_CONV = 1024
INVITES_PER_MIN = 60
REMOVES_PER_MIN = 60


@dataclass
class Conversation:
    conv_id: str
    owner_user_id: str
    created_at_ms: int


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._conversations: Dict[str, Conversation] = {}
        self._members: Dict[str, Dict[str, str]] = {}
        self._invite_limits = FixedWindowRateLimiter(INVITES_PER_MIN)
        self._remove_limits = FixedWindowRateLimiter(REMOVES_PER_MIN)

    def create(self, conv_id: str, owner_user_id: str, members: Iterable[str]) -> None:
        if conv_id in self._conversations:
            raise ValueError("conversation already exists")
        member_set = set(members)
        member_set.add(owner_user_id)
        if len(member_set) > MAX_MEMBERS_PER_CONV:
            raise LimitExceeded("too many members")
        conversation = Conversation(conv_id=conv_id, owner_user_id=owner_user_id, created_at_ms=_now_ms())
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

    def is_known(self, conv_id: str) -> bool:
        return conv_id in self._conversations

    def _require_conversation(self, conv_id: str) -> Conversation:
        conversation = self._conversations.get(conv_id)
        if conversation is None:
            raise ValueError("unknown conversation")
        return conversation

    def _require_admin(self, conversation: Conversation, actor_user_id: str) -> None:
        role = self.role(conversation.conv_id, actor_user_id)
        if role not in ("owner", "admin"):
            raise PermissionError("forbidden")


class SQLiteConversationStore:
    def __init__(self, backend: SQLiteBackend) -> None:
        self._backend = backend
        self._invite_limits = FixedWindowRateLimiter(INVITES_PER_MIN)
        self._remove_limits = FixedWindowRateLimiter(REMOVES_PER_MIN)

    def create(self, conv_id: str, owner_user_id: str, members: Iterable[str]) -> None:
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
                    "INSERT INTO conversations (conv_id, owner_user_id, created_at_ms) VALUES (?, ?, ?)",
                    (conv_id, owner_user_id, now_ms),
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

    def _require_conversation(self, conv_id: str) -> Conversation:
        with self._backend.lock:
            row = self._backend.connection.execute(
                "SELECT conv_id, owner_user_id, created_at_ms FROM conversations WHERE conv_id=?",
                (conv_id,),
            ).fetchone()
        if row is None:
            raise ValueError("unknown conversation")
        return Conversation(conv_id=row[0], owner_user_id=row[1], created_at_ms=row[2])

    def _require_admin(self, conversation: Conversation, actor_user_id: str) -> None:
        role = self.role(conversation.conv_id, actor_user_id)
        if role not in ("owner", "admin"):
            raise PermissionError("forbidden")
