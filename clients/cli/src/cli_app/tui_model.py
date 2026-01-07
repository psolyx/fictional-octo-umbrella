"""Pure-Python state machine for the MLS harness TUI."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from cli_app.identity_store import (
    DEFAULT_IDENTITY_PATH,
    IdentityRecord,
    load_or_create_identity,
    rotate_device,
)

DEFAULT_SETTINGS_FILE = Path.home() / ".mls_tui_state.json"
DM_FIELD_MAP = {
    "dm_state_dir": "state_dir",
    "dm_name": "name",
    "dm_seed": "seed",
    "dm_group_id": "group_id",
    "dm_peer_keypackage": "peer_keypackage",
    "dm_self_keypackage": "self_keypackage",
    "dm_welcome": "welcome",
    "dm_commit": "commit",
    "dm_plaintext": "plaintext",
    "dm_ciphertext": "ciphertext",
}


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
        }

        self.fields: Dict[str, str] = defaults
        self.focus_area = "menu"  # menu -> fields -> conversations -> transcript -> compose
        self.selected_menu = 0
        self.active_field = 0
        self.transcript_scroll = 0
        self.compose_text = ""

        self.dm_conversations = self._load_conversations(initial_settings, defaults)
        self.selected_conversation = self._load_selected_conversation(initial_settings)
        self._sync_fields_from_selected()

    def _persist(self) -> None:
        settings = dict(self.fields)
        settings["dm_conversations"] = self.dm_conversations
        settings["dm_selected"] = self.selected_conversation
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
                "peer_keypackage": defaults.get("dm_peer_keypackage", ""),
                "self_keypackage": defaults.get("dm_self_keypackage", ""),
                "welcome": defaults.get("dm_welcome", ""),
                "commit": defaults.get("dm_commit", ""),
                "group_id": defaults.get("dm_group_id", ""),
                "seed": defaults.get("dm_seed", "1337"),
                "plaintext": defaults.get("dm_plaintext", ""),
                "ciphertext": defaults.get("dm_ciphertext", ""),
            },
            "dm1",
        )

    def _normalize_conversation(self, entry: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
        transcript = entry.get("transcript", [])
        if not isinstance(transcript, list):
            transcript = []
        normalized = {
            "name": str(entry.get("name") or fallback_name),
            "state_dir": str(entry.get("state_dir", "")),
            "peer_keypackage": str(entry.get("peer_keypackage", "")),
            "self_keypackage": str(entry.get("self_keypackage", "")),
            "welcome": str(entry.get("welcome", "")),
            "commit": str(entry.get("commit", "")),
            "group_id": str(entry.get("group_id", "")),
            "seed": str(entry.get("seed", "1337")),
            "plaintext": str(entry.get("plaintext", "")),
            "ciphertext": str(entry.get("ciphertext", "")),
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
        for field_key, conv_key in DM_FIELD_MAP.items():
            self.fields[field_key] = str(conv.get(conv_key, ""))

    def focus_next(self) -> None:
        order = ["menu", "fields", "conversations", "transcript", "compose"]
        idx = order.index(self.focus_area)
        self.focus_area = order[(idx + 1) % len(order)]

    def focus_prev(self) -> None:
        order = ["menu", "fields", "conversations", "transcript", "compose"]
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

    def update_field_value(self, new_value: str) -> None:
        field_key = self.field_order[self.active_field]
        self.fields[field_key] = new_value
        if field_key in DM_FIELD_MAP:
            conv = self.get_selected_conv()
            conv[DM_FIELD_MAP[field_key]] = new_value
        self._persist()

    def set_field_value(self, field_key: str, new_value: str) -> None:
        self.fields[field_key] = new_value
        if field_key in DM_FIELD_MAP:
            conv = self.get_selected_conv()
            conv[DM_FIELD_MAP[field_key]] = new_value
        self._persist()

    def get_selected_conv(self) -> Dict[str, Any]:
        if not self.dm_conversations:
            self.dm_conversations = [self._build_default_conversation(self.fields)]
            self.selected_conversation = 0
        return self.dm_conversations[self.selected_conversation]

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

    def add_conv(self, name: str, state_dir: str) -> None:
        label = name.strip() if name.strip() else f"dm{len(self.dm_conversations) + 1}"
        conversation = self._normalize_conversation(
            {
                "name": label,
                "state_dir": state_dir,
                "seed": self.fields.get("dm_seed", "1337"),
                "group_id": self.fields.get("dm_group_id", ""),
                "peer_keypackage": "",
                "self_keypackage": "",
                "welcome": "",
                "commit": "",
                "plaintext": "",
                "ciphertext": "",
            },
            label,
        )
        self.dm_conversations.append(conversation)
        self.selected_conversation = len(self.dm_conversations) - 1
        self.transcript_scroll = 0
        self._sync_fields_from_selected()
        self._persist()

    def append_transcript(self, direction: str, text: str) -> None:
        conv = self.get_selected_conv()
        transcript = conv.setdefault("transcript", [])
        transcript.append({"ts": time.time(), "dir": direction, "text": text})
        if len(transcript) > self.max_log_lines:
            conv["transcript"] = transcript[-self.max_log_lines :]
        self.transcript_scroll = 0
        self._persist()

    def refresh_identity(self, record: IdentityRecord) -> None:
        self.identity = record

    def rotate_device(self) -> IdentityRecord:
        self.identity = rotate_device(self.identity_path)
        return self.identity

    def handle_key(self, key: str, char: Optional[str] = None) -> Optional[str]:
        """Handle a normalized key and return an action string when needed."""

        if key == "q":
            return "quit"
        if key == "TAB":
            self.focus_next()
            return None
        if key == "SHIFT_TAB":
            self.focus_prev()
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
            elif key in {"BACKSPACE", "DELETE"}:
                field_key = self.field_order[self.active_field]
                self.update_field_value(self.fields[field_key][:-1])
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
            if key in {"BACKSPACE", "DELETE"}:
                self.compose_text = self.compose_text[:-1]
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
        return RenderState(
            focus_area=self.focus_area,
            selected_menu=self.selected_menu,
            menu_items=list(self.menu_items),
            dm_conversations=[
                {"name": str(conv.get("name", "")), "state_dir": str(conv.get("state_dir", ""))}
                for conv in self.dm_conversations
            ],
            selected_conversation=self.selected_conversation,
            field_order=list(self.field_order),
            fields=dict(self.fields),
            active_field=self.active_field,
            transcript=transcript,
            transcript_scroll=self.transcript_scroll,
            compose_text=self.compose_text,
            user_id=self.identity.user_id,
            device_id=self.identity.device_id,
            identity_path=self.identity_path,
        )
