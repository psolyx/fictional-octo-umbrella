"""Pure-Python state machine for the MLS harness TUI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from cli_app.identity_store import (
    DEFAULT_IDENTITY_PATH,
    IdentityRecord,
    load_or_create_identity,
    rotate_device,
)

DEFAULT_SETTINGS_FILE = Path.home() / ".mls_tui_state.json"


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


def load_settings(path: Path | str = DEFAULT_SETTINGS_FILE) -> Dict[str, str]:
    """Load persisted TUI settings from disk if present."""

    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def persist_settings(settings: Dict[str, str], path: Path | str = DEFAULT_SETTINGS_FILE) -> None:
    """Persist the latest settings to disk."""

    payload = json.dumps(settings, indent=2, sort_keys=True)
    _atomic_write(Path(path).expanduser(), payload)


@dataclass
class RenderState:
    focus_area: str
    selected_menu: int
    menu_items: List[str]
    field_order: List[str]
    fields: Dict[str, str]
    active_field: int
    log_lines: List[str]
    log_scroll: int
    user_id: str
    device_id: str
    identity_path: Path


class TuiModel:
    """Minimal state machine backing the curses TUI."""

    def __init__(
        self,
        initial_settings: Dict[str, str],
        settings_path: Path | str = DEFAULT_SETTINGS_FILE,
        max_log_lines: int = 500,
        identity: IdentityRecord | None = None,
        identity_path: Path | str = DEFAULT_IDENTITY_PATH,
    ) -> None:
        self.menu_items: List[str] = [
            "vectors",
            "smoke",
            "soak",
            "social_publish",
            "social_feed",
            "rotate_device",
            "quit",
        ]
        self.field_order: List[str] = [
            "state_dir",
            "iterations",
            "save_every",
            "vector_file",
            "gateway_url",
            "social_text",
            "feed_limit",
            "feed_user_id",
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
            "gateway_url": initial_settings.get("gateway_url", "http://127.0.0.1:8080"),
            "social_text": initial_settings.get("social_text", ""),
            "feed_limit": initial_settings.get("feed_limit", "5"),
            "feed_user_id": initial_settings.get("feed_user_id", ""),
        }

        self.fields: Dict[str, str] = defaults
        self.focus_area = "menu"  # menu -> fields -> log
        self.selected_menu = 0
        self.active_field = 0
        self.log_lines: List[str] = []
        self.log_scroll = 0

    def _persist(self) -> None:
        persist_settings(self.fields, self.settings_path)

    def focus_next(self) -> None:
        order = ["menu", "fields", "log"]
        idx = order.index(self.focus_area)
        self.focus_area = order[(idx + 1) % len(order)]

    def focus_prev(self) -> None:
        order = ["menu", "fields", "log"]
        idx = order.index(self.focus_area)
        self.focus_area = order[(idx - 1) % len(order)]

    def move_menu(self, delta: int) -> None:
        self.selected_menu = (self.selected_menu + delta) % len(self.menu_items)

    def move_field(self, delta: int) -> None:
        self.active_field = max(0, min(len(self.field_order) - 1, self.active_field + delta))

    def scroll_log(self, delta: int) -> None:
        max_scroll = max(0, len(self.log_lines) - 1)
        self.log_scroll = max(0, min(max_scroll, self.log_scroll + delta))

    def update_field_value(self, new_value: str) -> None:
        field_key = self.field_order[self.active_field]
        self.fields[field_key] = new_value
        self._persist()

    def append_log(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.log_lines.append(line.rstrip("\n"))
        if len(self.log_lines) > self.max_log_lines:
            self.log_lines = self.log_lines[-self.max_log_lines :]
        self.log_scroll = 0

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

        if self.focus_area == "log":
            if key == "UP":
                self.scroll_log(1)
            elif key == "DOWN":
                self.scroll_log(-1)
            return None

        return None

    def current_action(self) -> str:
        return self.menu_items[self.selected_menu]

    def render(self) -> RenderState:
        return RenderState(
            focus_area=self.focus_area,
            selected_menu=self.selected_menu,
            menu_items=list(self.menu_items),
            field_order=list(self.field_order),
            fields=dict(self.fields),
            active_field=self.active_field,
            log_lines=list(self.log_lines),
            log_scroll=self.log_scroll,
            user_id=self.identity.user_id,
            device_id=self.identity.device_id,
            identity_path=self.identity_path,
        )
