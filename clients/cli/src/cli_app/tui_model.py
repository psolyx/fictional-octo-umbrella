"""Pure-Python state machine for the TUI (DM client + harness)."""

from __future__ import annotations

import json
import os
import secrets
import uuid
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from cli_app import gateway_store
from cli_app.identity_store import (
    DEFAULT_IDENTITY_PATH,
    IdentityRecord,
    load_or_create_identity,
    rotate_device,
)
from cli_app.redact import redact_text

DEFAULT_SETTINGS_FILE = Path.home() / ".mls_tui_state.json"
MODE_DM_CLIENT = "DM_CLIENT"
MODE_HARNESS = "HARNESS"
NEW_DM_FIELD_ORDER = ["peer_user_id", "name", "state_dir", "conv_id"]
ROOM_CREATE_FIELD_ORDER = ["name", "members", "conv_id", "state_dir"]
ROOM_MEMBERS_FIELD_ORDER = ["members"]


def _atomic_write(path: Path | str, content: str) -> None:
    """Write content atomically to ``path`` using fsync + rename."""

    path = Path(path).expanduser()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(path)


def load_settings(path: Path | str = DEFAULT_SETTINGS_FILE) -> Dict[str, Any]:
    """Load persisted TUI settings from disk if present."""

    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def persist_settings(settings: Dict[str, Any], path: Path | str = DEFAULT_SETTINGS_FILE) -> None:
    """Persist the latest settings to disk."""

    payload = json.dumps(settings, indent=2, sort_keys=True)
    _atomic_write(Path(path).expanduser(), payload)


@dataclass
class RenderState:
    mode: str
    focus_area: str
    selected_menu: int
    menu_items: List[str]
    dm_conversations: List[Dict[str, str]]
    selected_conversation: int
    field_order: List[str]
    fields: Dict[str, str]
    active_field: int
    transcript: List[Dict[str, Any]]
    transcript_scroll: int
    compose_text: str
    new_dm_active: bool
    new_dm_fields: Dict[str, str]
    new_dm_field_order: List[str]
    new_dm_active_field: int
    room_modal_active: bool
    room_modal_action: str
    room_modal_fields: Dict[str, str]
    room_modal_field_order: List[str]
    room_modal_active_field: int
    room_modal_error_line: str
    room_roster_active: bool
    room_roster_members: List[Dict[str, str]]
    room_roster_selected_idx: int
    help_overlay_active: bool
    social_active: bool
    social_target: str
    social_view_mode: str
    social_items: List[Dict[str, Any]]
    social_selected_idx: int
    social_scroll: int
    social_status_line: str
    social_compose_active: bool
    social_compose_text: str
    social_prev_hash: Optional[str]
    profile_user_id: str
    profile_data: Dict[str, Any]
    profile_selected_section: str
    feed_items: List[Dict[str, Any]]
    feed_cursor: Optional[str]
    feed_sources: List[str]
    social_edit_active: bool
    social_edit_field: int
    social_edit_fields: Dict[str, str]
    social_publish_queue: List[Dict[str, Any]]
    social_last_publish_error: Optional[str]
    presence_active: bool
    presence_enabled: bool
    presence_invisible: bool
    presence_items: List[Dict[str, Any]]
    presence_selected_idx: int
    presence_scroll: int
    presence_status_line: str
    presence_prompt_active: bool
    presence_prompt_action: str
    presence_prompt_text: str
    user_id: str
    device_id: str
    identity_path: Path


class TuiModel:
    """Minimal state machine backing the curses TUI."""

    def __init__(
        self,
        initial_settings: Dict[str, Any],
        settings_path: Path | str = DEFAULT_SETTINGS_FILE,
        max_log_lines: int = 500,
        identity: IdentityRecord | None = None,
        identity_path: Path | str = DEFAULT_IDENTITY_PATH,
    ) -> None:
        self.menu_items: List[str] = [
            "vectors",
            "smoke",
            "soak",
            "dm_keypackage",
            "dm_init",
            "dm_join",
            "dm_commit_apply",
            "dm_encrypt",
            "dm_decrypt",
            "gw_start",
            "gw_resume",
            "identity_export",
            "identity_import",
            "identity_new",
            "logout",
            "rotate_device",
            "quit",
        ]
        self.field_order: List[str] = [
            "state_dir",
            "iterations",
            "save_every",
            "vector_file",
            "dm_state_dir",
            "dm_name",
            "dm_seed",
            "dm_group_id",
            "dm_peer_keypackage",
            "dm_self_keypackage",
            "dm_welcome",
            "dm_commit",
            "dm_plaintext",
            "dm_ciphertext",
            "gateway_base_url",
            "identity_import_json",
        ]
        self.settings_path = Path(settings_path)
        self.max_log_lines = max_log_lines
        self.identity_path = Path(identity_path).expanduser()

        self.identity = identity if identity is not None else load_or_create_identity(self.identity_path)

        defaults = {
            "state_dir": initial_settings.get("state_dir", ""),
            "iterations": initial_settings.get("iterations", "50"),
            "save_every": initial_settings.get("save_every", "10"),
            "vector_file": initial_settings.get("vector_file", ""),
            "dm_state_dir": initial_settings.get("dm_state_dir", ""),
            "dm_name": initial_settings.get("dm_name", ""),
            "dm_seed": initial_settings.get("dm_seed", "1337"),
            "dm_group_id": initial_settings.get("dm_group_id", "ZHMtZG0tZ3JvdXA="),
            "dm_peer_keypackage": initial_settings.get("dm_peer_keypackage", ""),
            "dm_self_keypackage": initial_settings.get("dm_self_keypackage", ""),
            "dm_welcome": initial_settings.get("dm_welcome", ""),
            "dm_commit": initial_settings.get("dm_commit", ""),
            "dm_plaintext": initial_settings.get("dm_plaintext", ""),
            "dm_ciphertext": initial_settings.get("dm_ciphertext", ""),
            "gateway_base_url": initial_settings.get("gateway_base_url", "http://localhost:8787"),
            "identity_import_json": initial_settings.get("identity_import_json", ""),
        }

        self.fields: Dict[str, str] = defaults
        self.focus_area = "conversations"  # menu -> fields -> conversations -> transcript -> compose
        self.selected_menu = 0
        self.active_field = 0
        self.transcript_scroll = 0
        self.compose_text = ""
        self.mode = initial_settings.get("tui_mode")
        if self.mode not in {MODE_DM_CLIENT, MODE_HARNESS}:
            mode_fallback = MODE_DM_CLIENT
            if (
                "tui_mode" not in initial_settings
                and self.settings_path != DEFAULT_SETTINGS_FILE
                and self.settings_path.exists()
                and self.settings_path.stat().st_size == 0
            ):
                mode_fallback = MODE_HARNESS
            self.mode = mode_fallback
        self.new_dm_active = False
        self.new_dm_fields = {"peer_user_id": "", "name": "", "state_dir": "", "conv_id": ""}
        self.new_dm_active_field = 0
        self.room_modal_active = False
        self.room_modal_action = ""
        self.room_modal_fields = {}
        self.room_modal_field_order = []
        self.room_modal_active_field = 0
        self.room_modal_error_line = ""
        self.room_roster_active = False
        self.room_roster_members: List[Dict[str, str]] = []
        self.room_roster_selected_idx = 0
        self.help_overlay_active = False

        self.social_active = False
        self.social_target = "self"
        self.social_view_mode = "events"
        self.social_items: List[Dict[str, Any]] = []
        self.social_selected_idx = 0
        self.social_scroll = 0
        self.social_status_line = ""
        self.social_compose_active = False
        self.social_compose_text = ""
        self.social_prev_hash: Optional[str] = None
        self.profile_user_id = self.identity.social_public_key_b64
        self.profile_data: Dict[str, Any] = {}
        self.profile_selected_section = "friends"
        self.feed_items: List[Dict[str, Any]] = []
        self.feed_cursor: Optional[str] = None
        self.feed_sources: List[str] = []
        self.social_edit_active = False
        self.social_edit_field = 0
        self.social_edit_fields = {
            "username": "",
            "description": "",
            "avatar": "",
            "banner": "",
            "interests": "",
        }
        self.social_publish_queue: List[Dict[str, Any]] = []
        self.social_last_publish_error: Optional[str] = None

        self.presence_active = False
        self.presence_enabled = True
        self.presence_invisible = False
        self.presence_entries: Dict[str, Dict[str, Any]] = {}
        self.presence_selected_idx = 0
        self.presence_scroll = 0
        self.presence_status_line = ""
        self.presence_prompt_active = False
        self.presence_prompt_action = ""
        self.presence_prompt_text = ""

        self.dm_conversations = self._load_conversations(initial_settings, defaults)
        self.selected_conversation = self._load_selected_conversation(initial_settings)
        if self.mode == MODE_HARNESS:
            self.focus_area = "menu"
            self._sync_fields_from_selected()

    def _persist(self) -> None:
        settings: Dict[str, Any] = {}
        if self.mode == MODE_HARNESS:
            settings.update(self.fields)
        settings["dm_conversations"] = self.dm_conversations
        settings["dm_selected"] = self.selected_conversation
        settings["tui_mode"] = self.mode
        persist_settings(settings, self.settings_path)

    def _load_conversations(self, initial_settings: Dict[str, Any], defaults: Dict[str, str]) -> List[Dict[str, Any]]:
        stored = initial_settings.get("dm_conversations")
        if isinstance(stored, list) and stored:
            conversations = []
            for idx, entry in enumerate(stored):
                if not isinstance(entry, dict):
                    entry = {}
                conversations.append(self._normalize_conversation(entry, f"dm{idx + 1}"))
            return conversations
        return [self._build_default_conversation(defaults)]

    def _load_selected_conversation(self, initial_settings: Dict[str, Any]) -> int:
        selected = initial_settings.get("dm_selected", 0)
        if isinstance(selected, int):
            return max(0, min(selected, len(self.dm_conversations) - 1))
        return 0

    def _build_default_conversation(self, defaults: Dict[str, str]) -> Dict[str, Any]:
        return self._normalize_conversation(
            {
                "name": "dm1",
                "state_dir": defaults.get("dm_state_dir", ""),
                "peer_user_id": "",
                "conv_id": "",
                "next_seq": 1,
            },
            "dm1",
        )

    def _normalize_conversation(self, entry: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
        transcript = entry.get("transcript", [])
        if not isinstance(transcript, list):
            transcript = []
        conv_id = str(entry.get("conv_id") or entry.get("group_id") or "")
        next_seq = entry.get("next_seq")
        if not isinstance(next_seq, int):
            next_seq = gateway_store.get_next_seq(conv_id) if conv_id else 1
        normalized = {
            "name": str(entry.get("name") or fallback_name),
            "conv_id": conv_id,
            "state_dir": str(entry.get("state_dir", "")),
            "peer_user_id": str(entry.get("peer_user_id", "")),
            "next_seq": max(int(next_seq), 1),
            "label": str(entry.get("label") or entry.get("name") or fallback_name),
            "last_preview": str(entry.get("last_preview", "")),
            "last_ts_ms": int(entry.get("last_ts_ms", 0) or 0),
            "transcript": [
                {
                    "ts": float(item.get("ts", 0.0)),
                    "dir": str(item.get("dir", "sys")),
                    "text": str(item.get("text", "")),
                }
                for item in transcript
                if isinstance(item, dict)
            ],
        }
        return normalized

    def _sync_fields_from_selected(self) -> None:
        conv = self.get_selected_conv()
        self.fields["dm_state_dir"] = str(conv.get("state_dir", ""))
        self.fields["dm_name"] = str(conv.get("name", ""))

    def focus_next(self) -> None:
        if self.mode == MODE_HARNESS:
            order = ["menu", "fields", "conversations", "transcript", "compose"]
        else:
            order = ["conversations", "transcript", "compose"]
            if self.social_active:
                order.append("social")
            if self.presence_active:
                order.append("presence")
        if self.focus_area not in order:
            self.focus_area = order[0]
            return
        idx = order.index(self.focus_area)
        self.focus_area = order[(idx + 1) % len(order)]

    def focus_prev(self) -> None:
        if self.mode == MODE_HARNESS:
            order = ["menu", "fields", "conversations", "transcript", "compose"]
        else:
            order = ["conversations", "transcript", "compose"]
            if self.social_active:
                order.append("social")
            if self.presence_active:
                order.append("presence")
        if self.focus_area not in order:
            self.focus_area = order[0]
            return
        idx = order.index(self.focus_area)
        self.focus_area = order[(idx - 1) % len(order)]

    def move_menu(self, delta: int) -> None:
        self.selected_menu = (self.selected_menu + delta) % len(self.menu_items)

    def move_field(self, delta: int) -> None:
        self.active_field = max(0, min(len(self.field_order) - 1, self.active_field + delta))

    def scroll_transcript(self, delta: int) -> None:
        transcript = self.get_selected_conv().get("transcript", [])
        max_scroll = max(0, len(transcript) - 1)
        self.transcript_scroll = max(0, min(max_scroll, self.transcript_scroll + delta))

    def scroll_social(self, delta: int) -> None:
        if self.social_view_mode == "feed":
            visible = self.feed_items
        elif self.social_view_mode == "profile":
            section = self.profile_selected_section
            visible = []
            if section == "friends":
                visible = list(self.profile_data.get("friends", []))
            elif section == "bulletins":
                visible = list(self.profile_data.get("bulletins", []))
        else:
            visible = self.social_items
        max_scroll = max(0, len(visible) - 1)
        self.social_scroll = max(0, min(max_scroll, self.social_scroll + delta))
        self.social_selected_idx = max(0, len(visible) - 1 - self.social_scroll)

    def scroll_presence(self, delta: int) -> None:
        max_scroll = max(0, len(self.presence_entries) - 1)
        self.presence_scroll = max(0, min(max_scroll, self.presence_scroll + delta))
        self.presence_selected_idx = max(0, len(self.presence_entries) - 1 - self.presence_scroll)

    def update_field_value(self, new_value: str) -> None:
        field_key = self.field_order[self.active_field]
        self.fields[field_key] = new_value
        if field_key in {"dm_state_dir", "dm_name"}:
            conv = self.get_selected_conv()
            if field_key == "dm_state_dir":
                conv["state_dir"] = new_value
            if field_key == "dm_name":
                conv["name"] = new_value
        self._persist()

    def append_to_active_field(self, text: str) -> None:
        """Append text to the active field as a single persisted update.

        Terminal paste can arrive as hundreds of characters in quick
        succession. Persisting on every character (fsync+rename) is slow and
        increases the chance of the UI becoming unresponsive during paste.
        """

        if not text:
            return
        field_key = self.field_order[self.active_field]
        self.update_field_value(self.fields.get(field_key, "") + text)

    def append_to_compose(self, text: str) -> None:
        """Append text to the compose buffer."""

        if not text:
            return
        self.compose_text += text

    def set_field_value(self, field_key: str, new_value: str) -> None:
        self.fields[field_key] = new_value
        if field_key in {"dm_state_dir", "dm_name"}:
            conv = self.get_selected_conv()
            if field_key == "dm_state_dir":
                conv["state_dir"] = new_value
            if field_key == "dm_name":
                conv["name"] = new_value
        self._persist()

    def get_selected_conv(self) -> Dict[str, Any]:
        if not self.dm_conversations:
            self.dm_conversations = [self._build_default_conversation(self.fields)]
            self.selected_conversation = 0
        return self.dm_conversations[self.selected_conversation]

    def get_selected_conv_id(self) -> str:
        return str(self.get_selected_conv().get("conv_id", ""))

    def select_next_conv(self) -> None:
        if not self.dm_conversations:
            return
        self.selected_conversation = (self.selected_conversation + 1) % len(self.dm_conversations)
        self.transcript_scroll = 0
        self._sync_fields_from_selected()
        self._persist()

    def select_prev_conv(self) -> None:
        if not self.dm_conversations:
            return
        self.selected_conversation = (self.selected_conversation - 1) % len(self.dm_conversations)
        self.transcript_scroll = 0
        self._sync_fields_from_selected()
        self._persist()

    def select_next_unread_conv(self) -> bool:
        if not self.dm_conversations:
            return False
        total = len(self.dm_conversations)
        start = self.selected_conversation
        for offset in range(1, total + 1):
            idx = (start + offset) % total
            unread_count = int(self.dm_conversations[idx].get("unread_count") or 0)
            if unread_count > 0:
                self.selected_conversation = idx
                self.transcript_scroll = 0
                self._sync_fields_from_selected()
                self._persist()
                return True
        return False

    def add_conv(self, name: str, state_dir: str) -> None:
        label = name.strip() if name.strip() else f"dm{len(self.dm_conversations) + 1}"
        conversation = self._normalize_conversation(
            {
                "name": label,
                "state_dir": state_dir,
                "peer_user_id": "",
                "conv_id": "",
                "next_seq": 1,
            },
            label,
        )
        self.dm_conversations.append(conversation)
        self.selected_conversation = len(self.dm_conversations) - 1
        self.transcript_scroll = 0
        if self.mode == MODE_HARNESS:
            self._sync_fields_from_selected()
        self._persist()

    def add_dm(self, peer_user_id: str, name: str, state_dir: str, conv_id: str) -> Dict[str, Any]:
        label = name.strip() if name.strip() else f"dm{len(self.dm_conversations) + 1}"
        conv_id = conv_id.strip() if conv_id.strip() else f"dm_{secrets.token_urlsafe(8)}"
        conversation = self._normalize_conversation(
            {
                "name": label,
                "state_dir": state_dir,
                "peer_user_id": peer_user_id,
                "conv_id": conv_id,
            },
            label,
        )
        self.dm_conversations.append(conversation)
        self.selected_conversation = len(self.dm_conversations) - 1
        self.transcript_scroll = 0
        if self.mode == MODE_HARNESS:
            self._sync_fields_from_selected()
        self._persist()
        return conversation

    def find_conversation(self, conv_id: str) -> Dict[str, Any] | None:
        for conversation in self.dm_conversations:
            if str(conversation.get("conv_id", "")) == conv_id:
                return conversation
        return None

    def ensure_conversation(
        self,
        *,
        conv_id: str,
        name: str,
        state_dir: str,
        peer_user_id: str,
        next_seq: int = 1,
    ) -> Dict[str, Any]:
        existing = self.find_conversation(conv_id)
        if existing is not None:
            if not existing.get("name"):
                existing["name"] = name
            if not existing.get("state_dir"):
                existing["state_dir"] = state_dir
            if peer_user_id and not existing.get("peer_user_id"):
                existing["peer_user_id"] = peer_user_id
            if int(existing.get("next_seq") or 1) < next_seq:
                existing["next_seq"] = next_seq
            self._persist()
            return existing

        conversation = self._normalize_conversation(
            {
                "name": name,
                "state_dir": state_dir,
                "peer_user_id": peer_user_id,
                "conv_id": conv_id,
                "next_seq": next_seq,
            },
            name,
        )
        self.dm_conversations.append(conversation)
        self._persist()
        return conversation

    def append_message(self, conv_id: str, direction: str, text: str) -> None:
        conv = self.get_selected_conv()
        if conv_id:
            for item in self.dm_conversations:
                if item.get("conv_id") == conv_id:
                    conv = item
                    break
        transcript = conv.setdefault("transcript", [])
        transcript.append({"ts": time.time(), "dir": direction, "text": redact_text(text)})
        if len(transcript) > self.max_log_lines:
            conv["transcript"] = transcript[-self.max_log_lines :]
        self.transcript_scroll = 0
        self._persist()

    def append_transcript(self, direction: str, text: str) -> None:
        self.append_message(self.get_selected_conv_id(), direction, text)

    def update_conversation_preview(self, conv_id: str, preview: str, ts_ms: int | None = None) -> None:
        conv = self.find_conversation(conv_id)
        if conv is None:
            return
        if preview:
            conv["last_preview"] = preview
        conv["last_ts_ms"] = int(ts_ms if isinstance(ts_ms, int) else time.time() * 1000)
        self._persist()

    def append_pending_outbound(self, conv_id: str, msg_id: str, text: str) -> None:
        self.append_message(conv_id, "out", f"[pending msg_id={msg_id}] {text}")
        self.update_conversation_preview(conv_id, f"me: {text}")

    def mark_outbound_delivered(self, conv_id: str, msg_id: str, seq: int | None = None) -> bool:
        conv = self.find_conversation(conv_id)
        if conv is None:
            return False
        transcript = conv.get("transcript", [])
        for entry in reversed(transcript):
            text = str(entry.get("text", ""))
            if f"[pending msg_id={msg_id}]" in text or f"[failed msg_id={msg_id}]" in text:
                delivered_suffix = f" seq={seq}" if isinstance(seq, int) else ""
                entry["text"] = text.replace("[pending", "[delivered", 1).replace("[failed", "[delivered", 1) + delivered_suffix
                self._persist()
                return True
        return False

    def mark_outbound_failed(self, conv_id: str, msg_id: str, reason: str = "send failed") -> bool:
        conv = self.find_conversation(conv_id)
        if conv is None:
            return False
        transcript = conv.get("transcript", [])
        for entry in reversed(transcript):
            text = str(entry.get("text", ""))
            if f"[pending msg_id={msg_id}]" in text:
                entry["text"] = text.replace("[pending", "[failed", 1) + f" (Retry send: r msg_id={msg_id}; {reason})"
                self._persist()
                return True
        return False


    def bump_cursor(self, conv_id: str, acked_seq: int) -> int:
        next_seq = gateway_store.update_next_seq(conv_id, acked_seq)
        for item in self.dm_conversations:
            if item.get("conv_id") == conv_id:
                item["next_seq"] = next_seq
                break
        self._persist()
        return next_seq

    def refresh_identity(self, record: IdentityRecord) -> None:
        self.identity = record

    def rotate_device(self) -> IdentityRecord:
        self.identity = rotate_device(self.identity_path)
        return self.identity


    def _open_room_modal(self, action: str) -> None:
        self.room_modal_active = True
        self.room_modal_action = action
        self.room_modal_active_field = 0
        if action == "room_create":
            conv_id = f"conv_{uuid.uuid4().hex}"
            self.room_modal_field_order = list(ROOM_CREATE_FIELD_ORDER)
            self.room_modal_fields = {"name": "", "members": "", "conv_id": conv_id, "state_dir": ""}
        else:
            self.room_modal_field_order = list(ROOM_MEMBERS_FIELD_ORDER)
            self.room_modal_fields = {"members": ""}
        self.room_modal_error_line = ""
        self.focus_area = "room_modal"


    def set_room_roster(self, members: List[Dict[str, str]]) -> None:
        normalized: List[Dict[str, str]] = []
        for row in members:
            user_id = str(row.get("user_id", "")).strip()
            role = str(row.get("role", "")).strip()
            if not user_id or not role:
                continue
            entry = self.presence_entries.get(user_id, {})
            normalized.append({"user_id": user_id, "role": role, "presence_status": str(entry.get("status", "unavailable"))})
        self.room_roster_members = normalized
        self.room_roster_selected_idx = min(
            max(0, self.room_roster_selected_idx),
            max(0, len(self.room_roster_members) - 1),
        )

    def selected_room_roster_member(self) -> str:
        if not self.room_roster_members:
            return ""
        idx = min(max(0, self.room_roster_selected_idx), len(self.room_roster_members) - 1)
        return str(self.room_roster_members[idx].get("user_id", ""))

    def handle_key(self, key: str, char: Optional[str] = None) -> Optional[str]:
        """Handle a normalized key and return an action string when needed."""

        if key == "CHAR" and char == "?":
            key = "?"

        if self.help_overlay_active:
            if key in {"ESC", "q", "?"}:
                self.help_overlay_active = False
            return None

        if key == "?":
            self.help_overlay_active = True
            return None

        if key == "q":
            return "quit"
        if key == "t":
            self.mode = MODE_HARNESS if self.mode == MODE_DM_CLIENT else MODE_DM_CLIENT
            self.focus_area = "conversations" if self.mode == MODE_DM_CLIENT else "menu"
            self.new_dm_active = False
            self.room_modal_active = False
            self.room_roster_active = False
            self.social_active = False
            self.presence_active = False
            self.social_compose_active = False
            self.social_compose_text = ""
            self.presence_prompt_active = False
            self.presence_prompt_text = ""
            self._persist()
            return "toggle_mode"
        if key == "r":
            if self.mode == MODE_DM_CLIENT and self.focus_area == "social" and self.social_active:
                if self.social_view_mode == "profile":
                    return "social_profile_refresh"
                if self.social_view_mode == "feed":
                    return "social_feed_refresh"
                return "social_refresh"
            return "resume"
        if key == "CTRL_P" and self.mode == MODE_DM_CLIENT and not self.new_dm_active:
            if self.social_active:
                self.social_active = False
                self.presence_active = True
                self.focus_area = "presence"
            elif self.presence_active:
                self.presence_active = False
                self.focus_area = "conversations"
            else:
                self.social_active = True
                self.focus_area = "social"
            self.social_compose_active = False
            self.social_compose_text = ""
            self.presence_prompt_active = False
            self.presence_prompt_text = ""
            return "panel_toggle"
        if (self.new_dm_active or self.room_modal_active) and key in {"TAB", "SHIFT_TAB"}:
            return None
        if key == "TAB":
            self.focus_next()
            return None
        if key == "SHIFT_TAB":
            self.focus_prev()
            return None


        if self.mode == MODE_DM_CLIENT and self.room_roster_active:
            if key == "ESC":
                self.room_roster_active = False
                self.focus_area = "room_modal" if self.room_modal_active else "conversations"
                return None
            if key == "UP":
                self.room_roster_selected_idx = max(0, self.room_roster_selected_idx - 1)
                return None
            if key == "DOWN":
                self.room_roster_selected_idx = min(
                    max(0, len(self.room_roster_members) - 1),
                    self.room_roster_selected_idx + 1,
                )
                return None
            if key == "CHAR" and char in {"A"}:
                return "room_roster_add_selected"
            if key == "ENTER":
                return "room_roster_add_selected"
            return None



        if self.mode == MODE_DM_CLIENT and self.room_modal_active:
            if key == "ESC":
                self.room_modal_active = False
                self.room_modal_action = ""
                self.room_modal_fields = {}
                self.room_modal_field_order = []
                self.room_modal_error_line = ""
                self.focus_area = "conversations"
                return None
            if key == "UP":
                self.room_modal_active_field = max(0, self.room_modal_active_field - 1)
                return None
            if key == "DOWN":
                self.room_modal_active_field = min(len(self.room_modal_field_order) - 1, self.room_modal_active_field + 1)
                return None
            if key == "BACKSPACE":
                field_key = self.room_modal_field_order[self.room_modal_active_field]
                self.room_modal_fields[field_key] = self.room_modal_fields.get(field_key, "")[:-1]
                self.room_modal_error_line = ""
                return None
            if key == "DELETE":
                field_key = self.room_modal_field_order[self.room_modal_active_field]
                self.room_modal_fields[field_key] = ""
                self.room_modal_error_line = ""
                return None
            if key == "ENTER":
                if self.room_modal_active_field == len(self.room_modal_field_order) - 1:
                    return f"{self.room_modal_action}_submit"
                self.room_modal_active_field += 1
                return None
            if char:
                field_key = self.room_modal_field_order[self.room_modal_active_field]
                self.room_modal_fields[field_key] = self.room_modal_fields.get(field_key, "") + char
                self.room_modal_error_line = ""
                return None
            return None

        if self.mode == MODE_DM_CLIENT and self.new_dm_active:
            if key == "UP":
                self.new_dm_active_field = max(0, self.new_dm_active_field - 1)
                return None
            if key == "DOWN":
                self.new_dm_active_field = min(
                    len(NEW_DM_FIELD_ORDER) - 1,
                    self.new_dm_active_field + 1,
                )
                return None
            if key == "BACKSPACE":
                field_key = NEW_DM_FIELD_ORDER[self.new_dm_active_field]
                self.new_dm_fields[field_key] = self.new_dm_fields[field_key][:-1]
                return None
            if key == "DELETE":
                field_key = NEW_DM_FIELD_ORDER[self.new_dm_active_field]
                self.new_dm_fields[field_key] = ""
                return None
            if key == "ENTER":
                if self.new_dm_active_field == len(NEW_DM_FIELD_ORDER) - 1:
                    return "create_dm"
                self.new_dm_active_field += 1
                return None
            if char:
                field_key = NEW_DM_FIELD_ORDER[self.new_dm_active_field]
                self.new_dm_fields[field_key] += char
                return None
            return None

        if self.mode == MODE_DM_CLIENT:
            if self.focus_area == "presence" and self.presence_active:
                if self.presence_prompt_active:
                    if key == "ESC":
                        self.presence_prompt_active = False
                        self.presence_prompt_text = ""
                        self.presence_prompt_action = ""
                        return None
                    if key == "BACKSPACE":
                        self.presence_prompt_text = self.presence_prompt_text[:-1]
                        return None
                    if key == "DELETE":
                        self.presence_prompt_text = ""
                        return None
                    if key == "ENTER":
                        return "presence_prompt_submit"
                    if char:
                        self.presence_prompt_text += char
                        return None
                    return None
                if key == "UP":
                    self.scroll_presence(1)
                    return None
                if key == "DOWN":
                    self.scroll_presence(-1)
                    return None
                if key == "CHAR" and char in {"a", "A"}:
                    self.presence_prompt_active = True
                    self.presence_prompt_action = "watch"
                    self.presence_prompt_text = ""
                    return None
                if key == "CHAR" and char in {"r", "R"}:
                    self.presence_prompt_active = True
                    self.presence_prompt_action = "unwatch"
                    self.presence_prompt_text = ""
                    return None
                if key == "CHAR" and char in {"b"}:
                    self.presence_prompt_active = True
                    self.presence_prompt_action = "block"
                    self.presence_prompt_text = ""
                    return None
                if key == "CHAR" and char in {"B"}:
                    self.presence_prompt_active = True
                    self.presence_prompt_action = "unblock"
                    self.presence_prompt_text = ""
                    return None
                if key == "CHAR" and char in {"i", "I"}:
                    self.presence_invisible = not self.presence_invisible
                    return "presence_toggle_invisible"
                if key == "CHAR" and char in {"e", "E"}:
                    self.presence_enabled = not self.presence_enabled
                    return "presence_toggle_enabled"
                return None
            if self.focus_area == "social" and self.social_active:
                if self.social_edit_active:
                    order = ["username", "description", "avatar", "banner", "interests"]
                    if key == "ESC":
                        self.social_edit_active = False
                        return None
                    if key == "UP":
                        self.social_edit_field = max(0, self.social_edit_field - 1)
                        return None
                    if key == "DOWN":
                        self.social_edit_field = min(len(order) - 1, self.social_edit_field + 1)
                        return None
                    field = order[self.social_edit_field]
                    if key == "BACKSPACE":
                        self.social_edit_fields[field] = self.social_edit_fields[field][:-1]
                        return None
                    if key == "DELETE":
                        self.social_edit_fields[field] = ""
                        return None
                    if key == "ENTER":
                        return "social_profile_edit_submit"
                    if char:
                        self.social_edit_fields[field] += char
                    return None
                if self.social_compose_active:
                    if key == "ESC":
                        self.social_compose_active = False
                        self.social_compose_text = ""
                        return None
                    if key == "BACKSPACE":
                        self.social_compose_text = self.social_compose_text[:-1]
                        return None
                    if key == "DELETE":
                        self.social_compose_text = ""
                        return None
                    if key == "ENTER":
                        return "social_publish"
                    if char:
                        self.social_compose_text += char
                        return None
                    return None
                if key == "UP":
                    self.scroll_social(1)
                    return None
                if key == "DOWN":
                    self.scroll_social(-1)
                    return None
                if key == "r":
                    if self.social_view_mode == "feed":
                        return "social_feed_refresh"
                    if self.social_view_mode == "profile":
                        return "social_profile_refresh"
                    return "social_refresh"
                if key == "CHAR" and char in {"R"}:
                    return "social_publish_retry_failed"
                if key == "CHAR" and char in {"1"}:
                    self.social_target = "self"
                    return "social_target_self"
                if key == "CHAR" and char in {"2"}:
                    self.social_target = "peer"
                    return "social_target_peer"
                if key == "CHAR" and char in {"v", "V"}:
                    self.social_view_mode = "profile"
                    self.social_scroll = 0
                    self.social_selected_idx = 0
                    return "social_profile_refresh"
                if key == "CHAR" and char in {"f", "F"}:
                    self.social_view_mode = "feed"
                    self.social_scroll = 0
                    self.social_selected_idx = 0
                    return "social_feed_refresh"
                if key == "CHAR" and char in {"n", "N"} and self.social_view_mode == "feed":
                    return "social_feed_load_more"
                if key == "CHAR" and char in {"a", "A"}:
                    return "social_follow_add"
                if key == "CHAR" and char in {"u", "U"}:
                    return "social_follow_remove"
                if key == "CHAR" and char in {"p", "P"}:
                    self.social_compose_active = True
                    self.social_compose_text = ""
                    return None
                if key == "CHAR" and char in {"e", "E"}:
                    self.social_edit_active = True
                    self.social_edit_field = 0
                    return "social_profile_edit_start"
                if key == "CHAR" and char in {"s", "S"} and self.social_view_mode == "profile":
                    self.profile_selected_section = (
                        "bulletins" if self.profile_selected_section == "friends" else "friends"
                    )
                    self.social_scroll = 0
                    self.social_selected_idx = 0
                    return None
                if key == "CHAR" and char in {"d", "D"}:
                    return "social_start_dm"
                return None
            if key == "CTRL_N":
                self.new_dm_active = True
                self.new_dm_fields = {"peer_user_id": "", "name": "", "state_dir": "", "conv_id": ""}
                self.new_dm_active_field = 0
                self.focus_area = "new_dm"
                return None
            if key == "CTRL_R":
                self._open_room_modal("room_create")
                return None
            if key == "CHAR" and char in {"I"}:
                self._open_room_modal("room_invite")
                return None
            if key == "CHAR" and char in {"K"}:
                self._open_room_modal("room_remove")
                return None
            if key == "CHAR" and char in {"+"}:
                self._open_room_modal("room_promote")
                return None
            if key == "CHAR" and char in {"-"}:
                self._open_room_modal("room_demote")
                return None
            if key == "CHAR" and char in {"m", "M"}:
                return "room_roster_toggle"
            if key == "CHAR" and char in {"l", "L"}:
                return "conv_refresh"
            if key == "CHAR" and char in {"U"}:
                return "conv_next_unread"
            if key == "CHAR" and char in {"R"}:
                return "retry_failed_send"
            if self.focus_area == "conversations":
                if key == "UP":
                    self.select_prev_conv()
                elif key == "DOWN":
                    self.select_next_conv()
                return None
            if self.focus_area == "transcript":
                if key == "UP":
                    self.scroll_transcript(1)
                elif key == "DOWN":
                    self.scroll_transcript(-1)
                return None
            if self.focus_area == "compose":
                if key == "BACKSPACE":
                    self.compose_text = self.compose_text[:-1]
                elif key == "DELETE":
                    self.compose_text = ""
                elif key == "ENTER":
                    return "send"
                elif char:
                    self.compose_text += char
                return None
            return None

        if self.focus_area == "menu":
            if key == "UP":
                self.move_menu(-1)
            elif key == "DOWN":
                self.move_menu(1)
            elif key == "ENTER":
                if self.menu_items[self.selected_menu] == "quit":
                    return "quit"
                return "run"
            return None

        if self.focus_area == "fields":
            if key == "UP":
                self.move_field(-1)
            elif key == "DOWN":
                self.move_field(1)
            elif key == "BACKSPACE":
                field_key = self.field_order[self.active_field]
                self.update_field_value(self.fields[field_key][:-1])
            elif key == "DELETE":
                # Reserve Delete for clearing the entire active field.
                # This makes it practical to replace large blobs (ciphertext,
                # welcome/commit, keypackages) without holding Backspace.
                field_key = self.field_order[self.active_field]
                self.update_field_value("")
            elif key == "ENTER":
                return None
            elif char:
                field_key = self.field_order[self.active_field]
                self.update_field_value(self.fields[field_key] + char)
            return None

        if self.focus_area == "conversations":
            if key in {"UP", "CTRL_P"}:
                self.select_prev_conv()
            elif key in {"DOWN", "CTRL_N"}:
                self.select_next_conv()
            elif key == "CHAR" and char in {"n", "N"}:
                return "new_conv"
            return None

        if self.focus_area == "transcript":
            if key == "UP":
                self.scroll_transcript(1)
            elif key == "DOWN":
                self.scroll_transcript(-1)
            return None

        if self.focus_area == "compose":
            if key == "BACKSPACE":
                self.compose_text = self.compose_text[:-1]
            elif key == "DELETE":
                self.compose_text = ""
            elif key == "ENTER":
                return "send"
            elif char:
                self.compose_text += char
            return None

        return None

    def current_action(self) -> str:
        return self.menu_items[self.selected_menu]

    def render(self) -> RenderState:
        transcript = list(self.get_selected_conv().get("transcript", []))
        presence_items = [self.presence_entries[key] for key in sorted(self.presence_entries.keys())]
        return RenderState(
            mode=self.mode,
            focus_area=self.focus_area,
            selected_menu=self.selected_menu,
            menu_items=list(self.menu_items),
            dm_conversations=[
                {
                    "name": str(conv.get("name", "")),
                    "state_dir": str(conv.get("state_dir", "")),
                    "conv_id": str(conv.get("conv_id", "")),
                    "peer_user_id": str(conv.get("peer_user_id", "")),
                    "unread_count": str(conv.get("unread_count", "0")),
                    "label": str(conv.get("label", conv.get("name", ""))),
                    "last_preview": str(conv.get("last_preview", "")),
                    "last_ts_ms": str(conv.get("last_ts_ms", "0")),
                    "presence_status": str(
                        self.presence_entries.get(str(conv.get("peer_user_id", "")), {}).get("status", "")
                    ),
                }
                for conv in self.dm_conversations
            ],
            selected_conversation=self.selected_conversation,
            field_order=list(self.field_order),
            fields=dict(self.fields),
            active_field=self.active_field,
            transcript=transcript,
            transcript_scroll=self.transcript_scroll,
            compose_text=self.compose_text,
            new_dm_active=self.new_dm_active,
            new_dm_fields=dict(self.new_dm_fields),
            new_dm_field_order=list(NEW_DM_FIELD_ORDER),
            new_dm_active_field=self.new_dm_active_field,
            room_modal_active=self.room_modal_active,
            room_modal_action=self.room_modal_action,
            room_modal_fields=dict(self.room_modal_fields),
            room_modal_field_order=list(self.room_modal_field_order),
            room_modal_active_field=self.room_modal_active_field,
            room_modal_error_line=self.room_modal_error_line,
            room_roster_active=self.room_roster_active,
            room_roster_members=list(self.room_roster_members),
            room_roster_selected_idx=self.room_roster_selected_idx,
            help_overlay_active=self.help_overlay_active,
            social_active=self.social_active,
            social_target=self.social_target,
            social_view_mode=self.social_view_mode,
            social_items=list(self.social_items),
            social_selected_idx=self.social_selected_idx,
            social_scroll=self.social_scroll,
            social_status_line=self.social_status_line,
            social_compose_active=self.social_compose_active,
            social_compose_text=self.social_compose_text,
            social_prev_hash=self.social_prev_hash,
            profile_user_id=self.profile_user_id,
            profile_data=dict(self.profile_data),
            profile_selected_section=self.profile_selected_section,
            feed_items=list(self.feed_items),
            feed_cursor=self.feed_cursor,
            feed_sources=list(self.feed_sources),
            social_edit_active=self.social_edit_active,
            social_edit_field=self.social_edit_field,
            social_edit_fields=dict(self.social_edit_fields),
            social_publish_queue=list(self.social_publish_queue),
            social_last_publish_error=self.social_last_publish_error,
            presence_active=self.presence_active,
            presence_enabled=self.presence_enabled,
            presence_invisible=self.presence_invisible,
            presence_items=presence_items,
            presence_selected_idx=self.presence_selected_idx,
            presence_scroll=self.presence_scroll,
            presence_status_line=self.presence_status_line,
            presence_prompt_active=self.presence_prompt_active,
            presence_prompt_action=self.presence_prompt_action,
            presence_prompt_text=self.presence_prompt_text,
            user_id=self.identity.user_id,
            device_id=self.identity.device_id,
            identity_path=self.identity_path,
        )

    def set_presence_status(self, text: str) -> None:
        self.presence_status_line = redact_text(text)

    def ensure_presence_contact(self, user_id: str) -> None:
        if not user_id:
            return
        entry = self.presence_entries.get(user_id, {"user_id": user_id})
        entry.setdefault("status", "offline")
        self.presence_entries[user_id] = entry
        self.presence_scroll = 0
        self.presence_selected_idx = max(0, len(self.presence_entries) - 1)

    def remove_presence_contact(self, user_id: str) -> None:
        if not user_id:
            return
        self.presence_entries.pop(user_id, None)
        self.presence_scroll = 0
        self.presence_selected_idx = max(0, len(self.presence_entries) - 1)

    def update_presence_entry(
        self,
        user_id: str,
        status: str,
        expires_at: Optional[int],
        last_seen_bucket: Optional[str],
    ) -> None:
        if not user_id:
            return
        entry = self.presence_entries.get(user_id, {"user_id": user_id})
        entry["status"] = status
        if expires_at is not None:
            entry["expires_at"] = expires_at
        if last_seen_bucket is not None:
            entry["last_seen_bucket"] = last_seen_bucket
        self.presence_entries[user_id] = entry
