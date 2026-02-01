"""Curses-based TUI wrapper for the MLS harness and DM client."""

from __future__ import annotations

import asyncio
import base64
import curses
import io
import json
import queue
import re
import secrets
import sys
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, Iterable, Optional

import aiohttp

from cli_app import dm_envelope, gateway_client, gateway_store, social

from cli_app import mls_poc
from cli_app.tui_model import DEFAULT_SETTINGS_FILE, MODE_DM_CLIENT, MODE_HARNESS, TuiModel, load_settings


def _normalize_key(key: int) -> tuple[str, str | None]:
    if key in (curses.KEY_BTAB, 353):  # shift-tab variations
        return "SHIFT_TAB", None
    key_tab = getattr(curses, "KEY_TAB", 9)
    if key in (key_tab, 9):
        return "TAB", None
    if key in (curses.KEY_UP,):
        return "UP", None
    if key in (curses.KEY_DOWN,):
        return "DOWN", None
    if key in (curses.KEY_ENTER, 10, 13):
        return "ENTER", None
    if key in (curses.KEY_BACKSPACE, 127, 8):
        return "BACKSPACE", None
    # Forward-delete varies across platforms/terminfo.
    # - ncurses typically reports KEY_DC (often 330)
    # - some environments may not expose KEY_DC via Python's curses
    if key in (getattr(curses, "KEY_DC", 330), 330):
        return "DELETE", None
    if key == 14:  # ctrl-n
        return "CTRL_N", None
    if key == 16:  # ctrl-p
        return "CTRL_P", None
    if key == 19:  # ctrl-s
        return "CTRL_S", None
    if key == 27:
        return "ESC", None
    if key in (ord("r"), ord("R")):
        return "r", None
    if key in (ord("t"), ord("T")):
        return "t", None
    if key in (ord("q"), ord("Q")):
        return "q", None
    if 32 <= key <= 126:
        return "CHAR", chr(key)
    return "UNKNOWN", None


_BLOB_FIELDS = {
    "dm_peer_keypackage",
    "dm_self_keypackage",
    "dm_welcome",
    "dm_commit",
    "dm_ciphertext",
}

# Fields whose values are expected to be RFC 4648 Base64 blobs.
# When pasting, we strip any non-Base64 characters so users can copy
# rendered/wrapped text (including UI borders) and paste safely.
_BASE64_FIELDS = {
    "dm_peer_keypackage",
    "dm_self_keypackage",
    "dm_welcome",
    "dm_commit",
    "dm_ciphertext",
}

_RE_NON_BASE64 = re.compile(r"[^A-Za-z0-9+/=]+")

_FULL_PREVIEW_FIELDS = set(_BLOB_FIELDS)


def _condense_blob(value: str, head: int = 14, tail: int = 10) -> str:
    """Condense long blob-ish values for 1-line rendering."""

    if not value:
        return ""
    if len(value) <= head + tail + 3:
        return value
    return f"{value[:head]}…{value[-tail:]} (len={len(value)})"


def _wrap_chunks(value: str, width: int) -> list[str]:
    if width <= 0:
        return [value]
    return [value[i : i + width] for i in range(0, len(value), width)] or [""]


_RE_BRACKETED_PASTE = re.compile(r"\x1b\[(?:\?2004[hl]|200~|201~)")


def _sanitize_paste(raw: str, strip_all_whitespace: bool = True, *, base64_only: bool = False) -> str:
    """Sanitize terminal paste input.

    - Removes bracketed-paste control sequences (xterm-style).
    - Optionally strips *all* whitespace so wrapped selections (with newlines)
      paste cleanly into single-line fields.
    """

    if not raw:
        return ""
    # Remove the known bracketed paste markers (start/end) and enable/disable.
    raw = raw.replace("\x1b[200~", "").replace("\x1b[201~", "")
    raw = raw.replace("\x1b[?2004h", "").replace("\x1b[?2004l", "")
    # Defensive: remove any remaining CSI fragments related to bracketed paste.
    raw = _RE_BRACKETED_PASTE.sub("", raw)
    if strip_all_whitespace:
        raw = "".join(raw.split())
    else:
        raw = raw.replace("\r", "")
    if base64_only:
        raw = _RE_NON_BASE64.sub("", raw)
    return raw


def _drain_pending_input(stdscr: curses.window, limit: int = 8192) -> list[int]:
    """Read any immediately-available pending input bytes.

    We temporarily switch to non-blocking mode to drain the input buffer.
    This helps treat terminal paste as one logical edit.
    """

    pending: list[int] = []
    stdscr.nodelay(True)
    try:
        while len(pending) < limit:
            nxt = stdscr.getch()
            if nxt == -1:
                break
            pending.append(nxt)
    finally:
        stdscr.nodelay(False)
    return pending


def _build_default_settings() -> Dict[str, str]:
    repo_root = mls_poc.find_repo_root()
    default_vector = repo_root / "tools" / "mls_harness" / "vectors" / "dm_smoke_v1.json"
    return {
        "tui_mode": MODE_DM_CLIENT,
        "state_dir": "",
        "iterations": "50",
        "save_every": "10",
        "vector_file": str(default_vector),
        "dm_state_dir": "",
        "dm_name": "",
        "dm_seed": "1337",
        "dm_group_id": "ZHMtZG0tZ3JvdXA=",
        "dm_peer_keypackage": "",
        "dm_self_keypackage": "",
        "dm_welcome": "",
        "dm_commit": "",
        "dm_plaintext": "",
        "dm_ciphertext": "",
    }


def _render_text(window: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    max_y, max_x = window.getmaxyx()
    if 0 <= y < max_y:
        window.addnstr(y, x, text, max_x - x - 1, attr)

def _init_default_colors(stdscr: curses.window) -> None:
    """Respect the terminal's configured theme (e.g., Solarized Light).

    Some terminals/terminfo combinations will erase with a black background
    unless default colors are enabled. Using use_default_colors() allows -1
    to mean "terminal default" for fg/bg.
    """

    if not curses.has_colors():
        return
    try:
        curses.start_color()
    except curses.error:
        return
    try:
        curses.use_default_colors()
    except curses.error:
        # Not all curses builds expose/enable this; fall back to whatever
        # the terminal provides.
        pass
    # Ensure clears/erases use the default color pair rather than an implied
    # black background on some terminfo entries.
    try:
        stdscr.bkgd(" ", curses.color_pair(0))
    except curses.error:
        pass



def draw_screen(stdscr: curses.window, model: TuiModel) -> None:
    if model.render().mode == MODE_HARNESS:
        _draw_harness_screen(stdscr, model)
    else:
        _draw_dm_screen(stdscr, model)
    stdscr.refresh()


def _draw_dm_screen(stdscr: curses.window, model: TuiModel) -> None:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    left_width = min(40, max(24, max_x // 3))
    right_start = left_width + 1
    header_offset = 6
    render = model.render()
    compose_height = 4 if render.social_active or render.presence_active else 3
    transcript_height = max(3, max_y - header_offset - compose_height - 1)

    _render_text(stdscr, 0, 1, "DM client TUI (gateway-backed)")
    _render_text(
        stdscr,
        1,
        1,
        "Tab: focus | Ctrl-N: new DM | Enter: send | r: resume | Ctrl-P: panel | t: harness | q: quit",
    )
    _render_text(stdscr, 2, 1, f"user:   {render.user_id}")
    _render_text(stdscr, 3, 1, f"device: {render.device_id}")
    _render_text(stdscr, 4, 1, f"identity: {render.identity_path}")

    stdscr.vline(header_offset, left_width, curses.ACS_VLINE, max(1, max_y - header_offset))

    _render_text(stdscr, header_offset, 1, "Conversations")
    for idx, conv in enumerate(render.dm_conversations):
        attr = curses.A_REVERSE if (render.focus_area == "conversations" and idx == render.selected_conversation) else 0
        label = conv.get("name", "")
        subtitle = conv.get("peer_user_id", "")
        _render_text(stdscr, header_offset + 1 + idx * 2, 2, label, attr)
        if subtitle and header_offset + 2 + idx * 2 < max_y:
            _render_text(stdscr, header_offset + 2 + idx * 2, 4, subtitle[: left_width - 6], attr)

    form_start = header_offset + 1 + len(render.dm_conversations) * 2
    if render.new_dm_active and form_start < max_y - 2:
        _render_text(stdscr, form_start, 1, "New DM (Enter to advance, Enter on conv_id to submit)")
        y = form_start + 1
        for idx, field in enumerate(render.new_dm_field_order):
            if y >= max_y - 1:
                break
            value = render.new_dm_fields.get(field, "")
            attr = curses.A_REVERSE if idx == render.new_dm_active_field else 0
            _render_text(stdscr, y, 2, f"{field}: {value}", attr)
            y += 1

    transcript_top = header_offset
    stdscr.hline(transcript_top - 1, right_start, curses.ACS_HLINE, max_x - right_start)
    if render.social_active:
        header = (
            f"SOCIAL ({render.social_target}) — r refresh, p post, 1/2 target, Ctrl-P to switch"
        )
        _render_text(stdscr, transcript_top - 1, right_start + 2, header)
        visible_social = _visible_social(render.social_items, transcript_height, render.social_scroll)
        highlight_idx = max(0, len(visible_social) - 1 - render.social_scroll)
        for idx, entry in enumerate(visible_social):
            line = _format_social_event(entry)
            attr = curses.A_REVERSE if render.focus_area == "social" and idx == highlight_idx else 0
            _render_text(stdscr, transcript_top + idx, right_start + 1, line, attr)
    elif render.presence_active:
        header = (
            "PRESENCE — a watch, r unwatch, b block, B unblock, i invisible, e enable, Ctrl-P to switch"
        )
        _render_text(stdscr, transcript_top - 1, right_start + 2, header)
        visible_presence = _visible_presence(render.presence_items, transcript_height, render.presence_scroll)
        highlight_idx = max(0, len(visible_presence) - 1 - render.presence_scroll)
        for idx, entry in enumerate(visible_presence):
            line = _format_presence_entry(entry)
            attr = curses.A_REVERSE if render.focus_area == "presence" and idx == highlight_idx else 0
            _render_text(stdscr, transcript_top + idx, right_start + 1, line, attr)
    else:
        _render_text(stdscr, transcript_top - 1, right_start + 2, "Transcript (latest at bottom)")
        visible_transcript = _visible_transcript(render.transcript, transcript_height, render.transcript_scroll)
        highlight_idx = max(0, len(visible_transcript) - 1 - render.transcript_scroll)
        for idx, entry in enumerate(visible_transcript):
            line = _format_transcript_entry(entry)
            attr = curses.A_REVERSE if render.focus_area == "transcript" and idx == highlight_idx else 0
            _render_text(stdscr, transcript_top + idx, right_start + 1, line, attr)

    compose_top = transcript_top + transcript_height + 1
    stdscr.hline(compose_top - 1, right_start, curses.ACS_HLINE, max_x - right_start)
    if render.social_active:
        header = "Post (p to compose, Enter to publish, Esc to cancel)"
        if render.social_compose_active:
            header = "Post (Enter to publish, Esc to cancel)"
        _render_text(stdscr, compose_top - 1, right_start + 2, header)
        compose_attr = curses.A_REVERSE if render.focus_area == "social" else 0
        _render_text(stdscr, compose_top, right_start + 1, render.social_compose_text, compose_attr)
        _render_text(stdscr, compose_top + 1, right_start + 1, render.social_status_line)
    elif render.presence_active:
        invisible_label = "on" if render.presence_invisible else "off"
        enabled_label = "on" if render.presence_enabled else "off"
        header = f"Presence input ({render.presence_prompt_action or 'idle'}) — invisible {invisible_label}, enabled {enabled_label}"
        _render_text(stdscr, compose_top - 1, right_start + 2, header)
        compose_attr = curses.A_REVERSE if render.focus_area == "presence" else 0
        prompt_text = render.presence_prompt_text if render.presence_prompt_active else ""
        _render_text(stdscr, compose_top, right_start + 1, prompt_text, compose_attr)
        _render_text(stdscr, compose_top + 1, right_start + 1, render.presence_status_line)
    else:
        _render_text(stdscr, compose_top - 1, right_start + 2, "Compose (Enter to send)")
        compose_attr = curses.A_REVERSE if render.focus_area == "compose" else 0
        _render_text(stdscr, compose_top, right_start + 1, render.compose_text, compose_attr)


def _draw_harness_screen(stdscr: curses.window, model: TuiModel) -> None:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    left_width = min(40, max(24, max_x // 3))
    right_start = left_width + 1
    header_offset = 6
    compose_height = 3
    transcript_height = max(3, max_y - header_offset - compose_height - 1)

    render = model.render()

    _render_text(stdscr, 0, 1, "Phase 0.5 MLS harness TUI")
    _render_text(stdscr, 1, 1, "Tab: focus | Enter: run | r: resume | t: DM | q: quit | n: new DM")
    _render_text(stdscr, 2, 1, f"user:   {render.user_id}")
    _render_text(stdscr, 3, 1, f"device: {render.device_id}")
    _render_text(stdscr, 4, 1, f"identity: {render.identity_path}")

    stdscr.vline(header_offset, left_width, curses.ACS_VLINE, max(1, max_y - header_offset))

    _render_text(stdscr, header_offset, 1, "Conversations")
    for idx, conv in enumerate(render.dm_conversations):
        attr = curses.A_REVERSE if (render.focus_area == "conversations" and idx == render.selected_conversation) else 0
        label = conv.get("name", "")
        _render_text(stdscr, header_offset + 1 + idx, 2, label, attr)

    action_start = header_offset + 2 + len(render.dm_conversations)
    _render_text(stdscr, action_start, 1, "Actions")
    for idx, item in enumerate(render.menu_items):
        attr = curses.A_REVERSE if (render.focus_area == "menu" and idx == render.selected_menu) else 0
        _render_text(stdscr, action_start + 1 + idx, 2, f"{item}", attr)

    field_start = action_start + 2 + len(render.menu_items)
    _render_text(stdscr, field_start, 1, "Parameters")
    y = field_start + 1
    value_width = max(10, left_width - 6)  # indent + margin
    for idx, field in enumerate(render.field_order):
        if y >= max_y - 1:
            break

        value = render.fields.get(field, "")
        is_active = render.focus_area == "fields" and idx == render.active_field
        attr = curses.A_REVERSE if is_active else 0

        # For blob fields, render the full value (wrapped) when active so
        # users can copy/paste values without ellipses, even on narrow terminals.
        if is_active and field in _FULL_PREVIEW_FIELDS and value:
            _render_text(stdscr, y, 2, f"{field}:", attr)
            y += 1
            for chunk in _wrap_chunks(value, value_width):
                if y >= max_y - 1:
                    break
                _render_text(stdscr, y, 4, chunk, attr)
                y += 1
            continue

        # Default: keep the list compact.
        display = value
        if field in _BLOB_FIELDS and value:
            display = _condense_blob(value)
        label = f"{field}: {display}"
        _render_text(stdscr, y, 2, label, attr)
        y += 1

    transcript_top = header_offset
    stdscr.hline(transcript_top - 1, right_start, curses.ACS_HLINE, max_x - right_start)
    _render_text(stdscr, transcript_top - 1, right_start + 2, "Transcript (latest at bottom)")
    visible_transcript = _visible_transcript(render.transcript, transcript_height, render.transcript_scroll)
    highlight_idx = max(0, len(visible_transcript) - 1 - render.transcript_scroll)
    for idx, entry in enumerate(visible_transcript):
        line = _format_transcript_entry(entry)
        attr = curses.A_REVERSE if render.focus_area == "transcript" and idx == highlight_idx else 0
        _render_text(stdscr, transcript_top + idx, right_start + 1, line, attr)

    compose_top = transcript_top + transcript_height + 1
    stdscr.hline(compose_top - 1, right_start, curses.ACS_HLINE, max_x - right_start)
    _render_text(stdscr, compose_top - 1, right_start + 2, "Compose (Enter to send)")
    compose_attr = curses.A_REVERSE if render.focus_area == "compose" else 0
    _render_text(stdscr, compose_top, right_start + 1, render.compose_text, compose_attr)


def _visible_transcript(entries: Iterable[Dict[str, str]], height: int, scroll: int) -> list[Dict[str, str]]:
    collected = list(entries)
    if height <= 0:
        return []
    end = max(0, len(collected) - scroll)
    start = max(0, end - height)
    return collected[start:end]


def _visible_social(entries: Iterable[Dict[str, object]], height: int, scroll: int) -> list[Dict[str, object]]:
    collected = list(entries)
    if height <= 0:
        return []
    end = max(0, len(collected) - scroll)
    start = max(0, end - height)
    return collected[start:end]


def _visible_presence(entries: Iterable[Dict[str, object]], height: int, scroll: int) -> list[Dict[str, object]]:
    collected = list(entries)
    if height <= 0:
        return []
    end = max(0, len(collected) - scroll)
    start = max(0, end - height)
    return collected[start:end]


def _extract_single_output_line(lines: Iterable[str]) -> str | None:
    for line in reversed(list(lines)):
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _parse_dm_init_output(lines: Iterable[str]) -> tuple[str, str] | None:
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "welcome" in payload and "commit" in payload:
            return str(payload["welcome"]), str(payload["commit"])
    return None


def _format_transcript_entry(entry: Dict[str, str]) -> str:
    direction = entry.get("dir", "sys")
    text = entry.get("text", "")
    if direction == "out":
        prefix = "me"
    elif direction == "in":
        prefix = "peer"
    else:
        prefix = "sys"
    return f"{prefix}: {text}"


def _format_social_event(entry: Dict[str, object]) -> str:
    kind = str(entry.get("kind", ""))
    payload = entry.get("payload")
    text = ""
    if isinstance(payload, dict) and "text" in payload:
        text = str(payload.get("text", ""))
    elif payload is not None:
        try:
            text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        except TypeError:
            text = str(payload)
    text = text.replace("\n", " ").strip()
    if len(text) > 80:
        text = f"{text[:80]}…"
    hash_prefix = str(entry.get("event_hash", ""))[:8]
    suffix = f" #{hash_prefix}" if hash_prefix else ""
    return f"{kind}: {text}{suffix}".strip()


def _format_presence_entry(entry: Dict[str, object]) -> str:
    user_id = str(entry.get("user_id", ""))
    status = str(entry.get("status", "offline"))
    last_seen = str(entry.get("last_seen_bucket", ""))
    expires_at = entry.get("expires_at")
    expires_text = ""
    if isinstance(expires_at, int):
        try:
            expires_text = time.strftime("%H:%M:%S", time.localtime(expires_at / 1000))
        except (OSError, ValueError):
            expires_text = str(expires_at)
    parts = [user_id, status]
    if last_seen:
        parts.append(f"last:{last_seen}")
    if expires_text:
        parts.append(f"exp:{expires_text}")
    return " | ".join(part for part in parts if part)

def _blob_preview_lines(label: str, value: str, chunk: int = 64) -> list[str]:
    """Render a copy-friendly blob preview across multiple transcript lines."""

    header = f"{label} (len={len(value)}):"
    return [header] + _wrap_chunks(value, chunk)


@dataclass
class SessionState:
    base_url: str
    session_token: str
    resume_token: str


@dataclass
class TailThread:
    thread: threading.Thread
    stop_event: threading.Event


@dataclass
class PresenceThread:
    thread: threading.Thread
    stop_event: threading.Event


@dataclass
class DmRuntime:
    joined: bool
    pending_commits: dict[int, str]
    pending_path: Path
    dedupe_order: deque[str]
    dedupe_set: set[str]


def _generate_group_id_b64() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("utf-8")


def _run_dm_encrypt(model: TuiModel, log_writer: Callable[[Iterable[str]], None], plaintext: str) -> None:
    fields = model.render().fields
    if not fields.get("dm_state_dir"):
        log_writer(["dm_state_dir is required for dm_encrypt"])
        return
    if plaintext == "":
        log_writer(["dm_plaintext is required for dm_encrypt"])
        return
    args = SimpleNamespace(
        state_dir=fields.get("dm_state_dir", ""),
        plaintext=plaintext,
    )
    log_writer([f"dm_encrypt state_dir={args.state_dir}"])
    exit_code, output = _invoke(lambda: mls_poc.handle_dm_encrypt(args))
    if exit_code == 0:
        ciphertext = _extract_single_output_line(output)
        if ciphertext:
            model.set_field_value("dm_ciphertext", ciphertext)
            model.set_field_value("dm_plaintext", plaintext)
            model.append_transcript("out", plaintext)
            # Ciphertext can be very large; keep transcript readable.
            model.append_transcript(
                "out",
                f"[ciphertext] {ciphertext[:18]}…{ciphertext[-12:]} (len={len(ciphertext)})",
            )
            # Avoid logging the full ciphertext line into the transcript/log output.
            output = [line for line in output if line.strip() != ciphertext]
            output.append(f"dm_ciphertext_len={len(ciphertext)}")
    suffix = "ok" if exit_code == 0 else f"failed ({exit_code})"
    log_writer(output + [f"Completed: {suffix}"])


def _run_action(model: TuiModel, log_writer: Callable[[Iterable[str]], None]) -> None:
    action = model.current_action()
    fields = model.render().fields

    def _write_heading(lines: Iterable[str]) -> None:
        log_writer([f"== {action} =="])
        log_writer(lines)

    def _parse_int(value: str, field_name: str) -> int | None:
        try:
            return int(value)
        except ValueError:
            log_writer([f"Invalid {field_name}: {value!r} (expected integer)"])
            return None

    try:
        if action == "vectors":
            args = SimpleNamespace(vector_file=fields.get("vector_file", ""))
            _write_heading([f"vector_file={args.vector_file}"])
            exit_code, output = _invoke(lambda: mls_poc.handle_vectors(args))
        elif action == "smoke":
            iterations = _parse_int(fields.get("iterations", "0"), "iterations")
            save_every = _parse_int(fields.get("save_every", "0"), "save_every")
            if iterations is None or save_every is None:
                return
            if not fields.get("state_dir"):
                log_writer(["state_dir is required for smoke"])
                return
            args = SimpleNamespace(
                state_dir=fields.get("state_dir", ""),
                iterations=iterations,
                save_every=save_every,
            )
            _write_heading(
                [f"state_dir={args.state_dir}", f"iterations={args.iterations}", f"save_every={args.save_every}"]
            )
            exit_code, output = _invoke(lambda: mls_poc.handle_smoke(args))
        elif action == "soak":
            iterations = _parse_int(fields.get("iterations", "0"), "iterations")
            save_every = _parse_int(fields.get("save_every", "0"), "save_every")
            if iterations is None or save_every is None:
                return
            if not fields.get("state_dir"):
                log_writer(["state_dir is required for soak"])
                return
            args = SimpleNamespace(
                state_dir=fields.get("state_dir", ""),
                iterations=iterations,
                save_every=save_every,
            )
            _write_heading(
                [f"state_dir={args.state_dir}", f"iterations={args.iterations}", f"save_every={args.save_every}"]
            )
            exit_code, output = _invoke(lambda: mls_poc.handle_soak(args))
        elif action == "dm_keypackage":
            seed = _parse_int(fields.get("dm_seed", "0"), "dm_seed")
            if seed is None:
                return
            if not fields.get("dm_state_dir"):
                log_writer(["dm_state_dir is required for dm_keypackage"])
                return
            if not fields.get("dm_name"):
                log_writer(["dm_name is required for dm_keypackage"])
                return
            args = SimpleNamespace(
                state_dir=fields.get("dm_state_dir", ""),
                name=fields.get("dm_name", ""),
                seed=seed,
            )
            _write_heading([f"dm_state_dir={args.state_dir}", f"dm_name={args.name}", f"dm_seed={args.seed}"])
            exit_code, output = _invoke(lambda: mls_poc.handle_dm_keypackage(args))
            if exit_code == 0:
                keypackage = _extract_single_output_line(output)
                if keypackage:
                    model.set_field_value("dm_self_keypackage", keypackage)
                    # Also emit a copy-friendly multi-line preview in the transcript.
                    log_writer(_blob_preview_lines("dm_self_keypackage", keypackage))
        elif action == "dm_init":
            seed = _parse_int(fields.get("dm_seed", "0"), "dm_seed")
            if seed is None:
                return
            missing = []
            if not fields.get("dm_state_dir"):
                missing.append("dm_state_dir")
            if not fields.get("dm_peer_keypackage"):
                missing.append("dm_peer_keypackage")
            if not fields.get("dm_group_id"):
                missing.append("dm_group_id")
            if missing:
                log_writer([f"Missing required fields for dm_init: {', '.join(missing)}"])
                return
            args = SimpleNamespace(
                state_dir=fields.get("dm_state_dir", ""),
                peer_keypackage=fields.get("dm_peer_keypackage", ""),
                group_id=fields.get("dm_group_id", ""),
                seed=seed,
            )
            _write_heading(
                [
                    f"dm_state_dir={args.state_dir}",
                    f"dm_peer_keypackage_len={len(args.peer_keypackage)}",
                    f"dm_group_id={args.group_id}",
                    f"dm_seed={args.seed}",
                ]
            )
            exit_code, output = _invoke(lambda: mls_poc.handle_dm_init(args))
            if exit_code == 0:
                parsed = _parse_dm_init_output(output)
                if parsed:
                    welcome, commit = parsed
                    model.set_field_value("dm_welcome", welcome)
                    model.set_field_value("dm_commit", commit)
                    # Avoid logging the full dm_init JSON payload (welcome+commit) into the transcript.
                    output = [
                        f"dm_welcome_len={len(welcome)}",
                        f"dm_commit_len={len(commit)}",
                    ]
        elif action == "dm_join":
            if not fields.get("dm_state_dir"):
                log_writer(["dm_state_dir is required for dm_join"])
                return
            if not fields.get("dm_welcome"):
                log_writer(["dm_welcome is required for dm_join"])
                return
            args = SimpleNamespace(
                state_dir=fields.get("dm_state_dir", ""),
                welcome=fields.get("dm_welcome", ""),
            )
            _write_heading([f"dm_state_dir={args.state_dir}", f"dm_welcome_len={len(args.welcome)}"])
            exit_code, output = _invoke(lambda: mls_poc.handle_dm_join(args))
        elif action == "dm_commit_apply":
            if not fields.get("dm_state_dir"):
                log_writer(["dm_state_dir is required for dm_commit_apply"])
                return
            if not fields.get("dm_commit"):
                log_writer(["dm_commit is required for dm_commit_apply"])
                return
            args = SimpleNamespace(
                state_dir=fields.get("dm_state_dir", ""),
                commit=fields.get("dm_commit", ""),
            )
            _write_heading([f"dm_state_dir={args.state_dir}", f"dm_commit_len={len(args.commit)}"])
            exit_code, output = _invoke(lambda: mls_poc.handle_dm_commit_apply(args))
        elif action == "dm_encrypt":
            _run_dm_encrypt(model, log_writer, fields.get("dm_plaintext", ""))
            return
        elif action == "dm_decrypt":
            if not fields.get("dm_state_dir"):
                log_writer(["dm_state_dir is required for dm_decrypt"])
                return
            if not fields.get("dm_ciphertext"):
                log_writer(["dm_ciphertext is required for dm_decrypt"])
                return
            args = SimpleNamespace(
                state_dir=fields.get("dm_state_dir", ""),
                ciphertext=fields.get("dm_ciphertext", ""),
            )
            _write_heading([f"dm_state_dir={args.state_dir}", f"dm_ciphertext_len={len(args.ciphertext)}"])
            exit_code, output = _invoke(lambda: mls_poc.handle_dm_decrypt(args))
            if exit_code == 0:
                plaintext = _extract_single_output_line(output)
                if plaintext is not None:
                    model.set_field_value("dm_plaintext", plaintext)
                    model.append_transcript("in", plaintext)
        elif action == "rotate_device":
            record = model.rotate_device()
            _write_heading(
                [
                    f"new_device_id={record.device_id}",
                    "device_credential rotated",  # opaque placeholder for gateway session.start
                ]
            )
            exit_code, output = 0, []
        else:
            log_writer([f"Unknown action: {action}"])
            return
    except Exception as exc:  # pragma: no cover - defensive
        log_writer([f"Error while running {action}: {exc}"])
        return

    suffix = "ok" if exit_code == 0 else f"failed ({exit_code})"
    log_writer(output + [f"Completed: {suffix}"])


def _invoke(func: Callable[[], int]) -> tuple[int, list[str]]:
    buffer = io.StringIO()
    exit_code: int
    with _redirect_output(buffer):
        exit_code = func()
    buffer.seek(0)
    return exit_code, buffer.read().splitlines()


def _append_system_message(model: TuiModel, text: str) -> None:
    conv_id = model.get_selected_conv_id()
    model.append_message(conv_id, "sys", text)


def _set_social_status(model: TuiModel, text: str) -> None:
    model.social_status_line = text


def _load_social_base_url(model: TuiModel) -> str | None:
    stored = gateway_store.load_session()
    if stored is None:
        _append_system_message(model, "No stored gateway session. Run gw-start or gw-resume first.")
        _set_social_status(model, "No stored gateway session.")
        return None
    return stored["base_url"]


def _resolve_social_target(model: TuiModel) -> str | None:
    if model.social_target == "self":
        return model.identity.social_public_key_b64
    peer_user_id = str(model.get_selected_conv().get("peer_user_id", "")).strip()
    if not peer_user_id:
        _append_system_message(model, "Selected conversation has no peer_user_id.")
        _set_social_status(model, "Select a DM with a peer_user_id for peer timeline.")
        return None
    return peer_user_id


def _get_conv_by_id(model: TuiModel, conv_id: str) -> Optional[dict[str, object]]:
    for conv in model.dm_conversations:
        if conv.get("conv_id") == conv_id:
            return conv
    return None


def _ensure_runtime_state(runtime: dict[str, DmRuntime], conv_id: str, state_dir: str) -> DmRuntime:
    if conv_id in runtime:
        return runtime[conv_id]
    pending_path = mls_poc._pending_commits_path(state_dir)
    pending_commits = mls_poc._load_pending_commits(pending_path)
    joined = mls_poc._state_dir_has_data(Path(state_dir))
    if joined and pending_commits:
        mls_poc._flush_pending_commits(state_dir, pending_commits, pending_path)
    state = DmRuntime(
        joined=joined,
        pending_commits=pending_commits,
        pending_path=pending_path,
        dedupe_order=deque(),
        dedupe_set=set(),
    )
    runtime[conv_id] = state
    return state


def _record_msg_id(runtime: DmRuntime, msg_id: str, max_size: int = 512) -> bool:
    if msg_id in runtime.dedupe_set:
        return True
    runtime.dedupe_order.append(msg_id)
    runtime.dedupe_set.add(msg_id)
    if len(runtime.dedupe_order) > max_size:
        evicted = runtime.dedupe_order.popleft()
        runtime.dedupe_set.discard(evicted)
    return False


def _start_tail_thread(
    conv_id: str,
    session: SessionState,
    event_queue: queue.Queue[dict[str, object]],
    stop_event: threading.Event,
    *,
    idle_timeout_s: float = 1.0,
) -> threading.Thread:
    def _loop() -> None:
        from_seq = gateway_store.get_next_seq(conv_id)
        while not stop_event.is_set():
            from_seq = gateway_store.get_next_seq(conv_id)
            try:
                for event in gateway_client.sse_tail(
                    session.base_url,
                    session.session_token,
                    conv_id,
                    from_seq,
                    idle_timeout_s=idle_timeout_s,
                ):
                    if stop_event.is_set():
                        return
                    event_queue.put({"type": "conv", "conv_id": conv_id, "event": event})
                time.sleep(0.1)
            except Exception as exc:  # pragma: no cover - network tolerance
                event_queue.put({"type": "conv", "conv_id": conv_id, "error": str(exc)})
                time.sleep(0.5)

    thread = threading.Thread(target=_loop, name=f"dm-tail-{conv_id}", daemon=True)
    thread.start()
    return thread


def _resume_or_start_session(model: TuiModel) -> SessionState | None:
    stored = gateway_store.load_session()
    if stored is None:
        _append_system_message(model, "No stored gateway session. Run gw-start or gw-resume first.")
        return None
    base_url = stored["base_url"]
    resume_token = stored["resume_token"]
    try:
        response = gateway_client.session_resume(base_url, resume_token)
        session = SessionState(base_url=base_url, session_token=response["session_token"], resume_token=response["resume_token"])
        gateway_store.save_session(base_url, session.session_token, session.resume_token)
        _append_system_message(model, "Session resumed.")
        return session
    except Exception:
        identity = model.identity
        try:
            response = gateway_client.session_start(
                base_url,
                identity.auth_token,
                identity.device_id,
                identity.device_credential,
            )
        except Exception as exc:  # pragma: no cover - defensive
            _append_system_message(model, f"Session start failed: {exc}")
            return None
        session = SessionState(base_url=base_url, session_token=response["session_token"], resume_token=response["resume_token"])
        gateway_store.save_session(base_url, session.session_token, session.resume_token)
        _append_system_message(model, "Session started.")
        return session


def _handle_tail_event(
    model: TuiModel,
    runtime: dict[str, DmRuntime],
    session: SessionState,
    conv_id: str,
    event: dict[str, object],
) -> bool:
    body = event.get("body", {})
    if not isinstance(body, dict):
        return False
    seq = body.get("seq")
    env_b64 = body.get("env")
    msg_id = body.get("msg_id")
    if not isinstance(seq, int) or not isinstance(env_b64, str):
        return False
    conv = _get_conv_by_id(model, conv_id)
    if conv is None:
        return False
    state_dir = str(conv.get("state_dir", ""))
    if not state_dir:
        return False
    expected_seq = int(conv.get("next_seq", 1))
    if seq > expected_seq:
        model.append_message(conv_id, "sys", f"Gap detected at seq {seq}; resubscribing.")
        return True
    runtime_state = _ensure_runtime_state(runtime, conv_id, state_dir)
    if isinstance(msg_id, str) and _record_msg_id(runtime_state, msg_id):
        gateway_client.inbox_ack(session.base_url, session.session_token, conv_id, seq)
        model.bump_cursor(conv_id, seq)
        return False
    try:
        kind, payload_b64 = dm_envelope.unpack(env_b64)
        if kind == 0x01:
            mls_poc._run_harness_capture(
                "dm-join",
                [
                    "--state-dir",
                    state_dir,
                    "--welcome",
                    payload_b64,
                ],
            )
            runtime_state.joined = True
            if runtime_state.pending_commits:
                mls_poc._flush_pending_commits(state_dir, runtime_state.pending_commits, runtime_state.pending_path)
            model.append_message(conv_id, "sys", "Joined DM.")
        elif kind == 0x02:
            if not runtime_state.joined:
                mls_poc._buffer_pending_commit(runtime_state.pending_path, runtime_state.pending_commits, seq, payload_b64)
            else:
                returncode, stdout, stderr = mls_poc._run_harness_capture_with_status(
                    "dm-commit-apply",
                    [
                        "--state-dir",
                        state_dir,
                        "--commit",
                        payload_b64,
                    ],
                )
                if returncode != 0:
                    message = (stderr.strip() or stdout.strip()).lower()
                    if mls_poc._is_uninitialized_commit_error(message):
                        runtime_state.joined = False
                        mls_poc._buffer_pending_commit(
                            runtime_state.pending_path,
                            runtime_state.pending_commits,
                            seq,
                            payload_b64,
                        )
                    else:
                        model.append_message(conv_id, "sys", "Commit apply failed; see logs.")
                        return False
                else:
                    runtime_state.joined = True
        elif kind == 0x03:
            output = mls_poc._run_harness_capture(
                "dm-decrypt",
                [
                    "--state-dir",
                    state_dir,
                    "--ciphertext",
                    payload_b64,
                ],
            )
            plaintext = mls_poc._first_nonempty_line(output)
            model.append_message(conv_id, "in", plaintext)
        else:
            model.append_message(conv_id, "sys", f"Unknown DM envelope kind {kind}.")
    except Exception as exc:  # pragma: no cover - defensive
        model.append_message(conv_id, "sys", f"Failed to process event: {exc}")
        return False
    gateway_client.inbox_ack(session.base_url, session.session_token, conv_id, seq)
    model.bump_cursor(conv_id, seq)
    return False


def _presence_post(
    base_url: str,
    session_token: str,
    path: str,
    payload: Dict[str, object],
) -> Dict[str, object]:
    url = f"{base_url.rstrip('/')}{path}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {session_token}"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _presence_lease(
    base_url: str,
    session_token: str,
    device_id: str,
    ttl_seconds: int,
    invisible: bool,
) -> int:
    response = _presence_post(
        base_url,
        session_token,
        "/v1/presence/lease",
        {"device_id": device_id, "ttl_seconds": ttl_seconds, "invisible": invisible},
    )
    return int(response["expires_at"])


def _presence_renew(
    base_url: str,
    session_token: str,
    device_id: str,
    ttl_seconds: int,
    invisible: bool,
) -> int:
    response = _presence_post(
        base_url,
        session_token,
        "/v1/presence/renew",
        {"device_id": device_id, "ttl_seconds": ttl_seconds, "invisible": invisible},
    )
    return int(response["expires_at"])


def _presence_watch(
    base_url: str,
    session_token: str,
    contacts: list[str],
) -> Dict[str, object]:
    return _presence_post(base_url, session_token, "/v1/presence/watch", {"contacts": contacts})


def _presence_unwatch(
    base_url: str,
    session_token: str,
    contacts: list[str],
) -> Dict[str, object]:
    return _presence_post(base_url, session_token, "/v1/presence/unwatch", {"contacts": contacts})


def _presence_block(
    base_url: str,
    session_token: str,
    contacts: list[str],
) -> Dict[str, object]:
    return _presence_post(base_url, session_token, "/v1/presence/block", {"contacts": contacts})


def _presence_unblock(
    base_url: str,
    session_token: str,
    contacts: list[str],
) -> Dict[str, object]:
    return _presence_post(base_url, session_token, "/v1/presence/unblock", {"contacts": contacts})


def _start_presence_thread(
    base_url: str,
    identity: object,
    event_queue: queue.Queue[dict[str, object]],
    stop_event: threading.Event,
) -> threading.Thread:
    async def _presence_loop() -> None:
        while not stop_event.is_set():
            try:
                async with aiohttp.ClientSession() as session:
                    ws_url = f"{base_url.rstrip('/')}/v1/ws"
                    async with session.ws_connect(ws_url, heartbeat=20) as ws:
                        payload = {
                            "v": 1,
                            "t": "session.start",
                            "id": "presence-start",
                            "body": {
                                "auth_token": identity.auth_token,
                                "device_id": identity.device_id,
                                "device_credential": identity.device_credential,
                            },
                        }
                        await ws.send_json(payload)
                        while not stop_event.is_set():
                            msg = await ws.receive(timeout=1.0)
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    frame = json.loads(msg.data)
                                except json.JSONDecodeError:
                                    continue
                                if frame.get("t") == "presence.update":
                                    event_queue.put({"type": "presence", "event": frame})
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except Exception as exc:  # pragma: no cover - network tolerance
                event_queue.put({"type": "presence_error", "error": str(exc)})
            if stop_event.wait(1.0):
                break

    def _runner() -> None:
        asyncio.run(_presence_loop())

    thread = threading.Thread(target=_runner, name="presence-ws", daemon=True)
    thread.start()
    return thread


def _send_dm_message(
    model: TuiModel,
    session: SessionState | None,
    runtime: dict[str, DmRuntime],
    plaintext: str,
) -> None:
    if session is None:
        _append_system_message(model, "No active session. Press r to resume.")
        return
    conv = model.get_selected_conv()
    conv_id = str(conv.get("conv_id", "")).strip()
    state_dir = str(conv.get("state_dir", "")).strip()
    if not conv_id:
        _append_system_message(model, "Selected conversation has no conv_id.")
        return
    if not state_dir:
        _append_system_message(model, "Selected conversation has no state_dir.")
        return
    output = mls_poc._run_harness_capture(
        "dm-encrypt",
        [
            "--state-dir",
            state_dir,
            "--plaintext",
            plaintext,
        ],
    )
    ciphertext = mls_poc._first_nonempty_line(output)
    env_b64 = dm_envelope.pack(0x03, ciphertext)
    msg_id = mls_poc._msg_id_for_env(env_b64)
    gateway_client.inbox_send(session.base_url, session.session_token, conv_id, msg_id, env_b64)
    runtime_state = _ensure_runtime_state(runtime, conv_id, state_dir)
    _record_msg_id(runtime_state, msg_id)
    model.append_message(conv_id, "out", plaintext)


def _create_new_dm(
    model: TuiModel,
    session: SessionState | None,
    runtime: dict[str, DmRuntime],
    peer_user_id: str,
    name: str,
    state_dir: str,
    conv_id: str,
) -> None:
    if session is None:
        _append_system_message(model, "No active session. Press r to resume.")
        return
    if not peer_user_id or not name or not state_dir:
        _append_system_message(model, "New DM requires peer_user_id, name, and state_dir.")
        return
    conv_id = conv_id.strip() if conv_id.strip() else f"dm_{secrets.token_urlsafe(8)}"
    response = gateway_client.keypackages_fetch(session.base_url, session.session_token, peer_user_id, 1)
    keypackages = response.get("keypackages", [])
    if not keypackages:
        _append_system_message(model, f"No KeyPackages available for user {peer_user_id}.")
        return
    peer_kp = str(keypackages[0])
    gateway_client.room_create(session.base_url, session.session_token, conv_id, [peer_user_id])
    group_id = _generate_group_id_b64()
    output = mls_poc._run_harness_capture(
        "dm-init",
        [
            "--state-dir",
            state_dir,
            "--peer-keypackage",
            peer_kp,
            "--group-id",
            group_id,
            "--seed",
            "7331",
        ],
    )
    payload = json.loads(mls_poc._first_nonempty_line(output))
    welcome = str(payload["welcome"])
    commit = str(payload["commit"])
    welcome_env = dm_envelope.pack(0x01, welcome)
    commit_env = dm_envelope.pack(0x02, commit)
    mls_poc._send_envelope(session.base_url, session.session_token, conv_id, welcome_env)
    mls_poc._send_envelope(session.base_url, session.session_token, conv_id, commit_env)
    model.add_dm(peer_user_id, name, state_dir, conv_id)
    _ensure_runtime_state(runtime, conv_id, state_dir)
    model.append_message(conv_id, "sys", "DM created; waiting for echo.")


# Manual smoke (gateway-backed DM):
# 1) Start gateway and run `gw-start` to store a session.
# 2) Launch this TUI, press r to resume/start, Ctrl-N to create a DM, then send a message.
# 3) Restart the TUI and verify it tails from the stored next_seq cursor.


class _redirect_output:
    def __init__(self, buffer: io.StringIO) -> None:
        self.buffer = buffer
        self._stdout = sys.stdout
        self._stderr = sys.stderr

    def __enter__(self) -> None:  # pragma: no cover - thin wrapper
        sys.stdout = self.buffer
        sys.stderr = self.buffer

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - thin wrapper
        sys.stdout = self._stdout
        sys.stderr = self._stderr


def main() -> int:
    settings = _build_default_settings()
    settings.update(load_settings(DEFAULT_SETTINGS_FILE))
    model = TuiModel(settings, settings_path=DEFAULT_SETTINGS_FILE)

    def _runner(stdscr: curses.window) -> None:
        curses.curs_set(0)
        _init_default_colors(stdscr)
        stdscr.nodelay(False)
        stdscr.keypad(True)
        event_queue: queue.Queue[dict[str, object]] = queue.Queue()
        runtime_state: dict[str, DmRuntime] = {}
        tail_threads: dict[str, TailThread] = {}
        session_state: SessionState | None = None
        presence_thread: PresenceThread | None = None
        presence_lease_expires_at: Optional[int] = None
        presence_last_lease_attempt: float = 0.0
        presence_ttl_seconds = 120
        presence_renew_margin_seconds = 20

        def _stop_tail_threads() -> None:
            for tail in tail_threads.values():
                tail.stop_event.set()
            for tail in tail_threads.values():
                tail.thread.join(timeout=0.5)
            tail_threads.clear()

        def _stop_presence_thread() -> None:
            nonlocal presence_thread
            if presence_thread is None:
                return
            presence_thread.stop_event.set()
            presence_thread.thread.join(timeout=0.5)
            presence_thread = None

        def _ensure_tail_threads() -> None:
            if session_state is None or model.render().mode != MODE_DM_CLIENT:
                return
            for conv in model.dm_conversations:
                conv_id = str(conv.get("conv_id", "")).strip()
                if not conv_id or conv_id in tail_threads:
                    continue
                stop_event = threading.Event()
                thread = _start_tail_thread(conv_id, session_state, event_queue, stop_event)
                tail_threads[conv_id] = TailThread(thread=thread, stop_event=stop_event)

        def _ensure_presence_thread() -> None:
            nonlocal presence_thread
            if session_state is None or model.render().mode != MODE_DM_CLIENT or not model.presence_enabled:
                _stop_presence_thread()
                return
            if presence_thread is None:
                stop_event = threading.Event()
                thread = _start_presence_thread(session_state.base_url, model.identity, event_queue, stop_event)
                presence_thread = PresenceThread(thread=thread, stop_event=stop_event)

        def _drain_events() -> None:
            while True:
                try:
                    payload = event_queue.get_nowait()
                except queue.Empty:
                    break
                payload_type = payload.get("type")
                if payload_type == "conv":
                    conv_id = str(payload.get("conv_id", ""))
                    if not conv_id:
                        continue
                    if "error" in payload:
                        model.append_message(conv_id, "sys", "Tail error; retrying.")
                        continue
                    if session_state is None:
                        continue
                    event = payload.get("event")
                    if isinstance(event, dict):
                        gap = _handle_tail_event(model, runtime_state, session_state, conv_id, event)
                        if gap:
                            tail = tail_threads.get(conv_id)
                            if tail:
                                tail.stop_event.set()
                                tail.thread.join(timeout=0.2)
                                del tail_threads[conv_id]
                            _ensure_tail_threads()
                elif payload_type == "presence":
                    event = payload.get("event")
                    if isinstance(event, dict):
                        body = event.get("body", {})
                        if isinstance(body, dict):
                            user_id = str(body.get("user_id", ""))
                            status = str(body.get("status", "offline"))
                            expires_at = body.get("expires_at")
                            if not isinstance(expires_at, int):
                                expires_at = None
                            last_seen_bucket = body.get("last_seen_bucket")
                            if not isinstance(last_seen_bucket, str):
                                last_seen_bucket = None
                            model.update_presence_entry(user_id, status, expires_at, last_seen_bucket)
                elif payload_type == "presence_error":
                    error = str(payload.get("error", "presence error"))
                    model.set_presence_status(f"Presence WS error: {error}")

        def _refresh_social() -> None:
            base_url = _load_social_base_url(model)
            if base_url is None:
                return
            user_id = _resolve_social_target(model)
            if user_id is None:
                return
            _set_social_status(model, "Refreshing...")
            try:
                events = social.fetch_social_events(base_url, user_id=user_id, limit=50, after_hash=None)
            except Exception as exc:
                _set_social_status(model, f"Error: {exc}")
                return
            model.social_items = events
            if events:
                model.social_prev_hash = str(events[-1].get("event_hash", ""))
                model.social_selected_idx = len(events) - 1
                model.social_scroll = 0
            else:
                model.social_prev_hash = None
                model.social_selected_idx = 0
                model.social_scroll = 0
            _set_social_status(model, f"Last refresh {time.strftime('%H:%M:%S')}")

        def _publish_social() -> None:
            if model.social_target != "self":
                _set_social_status(model, "Posting is only available for the self timeline.")
                return
            text = model.social_compose_text.strip()
            if not text:
                _set_social_status(model, "Compose text is empty.")
                return
            base_url = _load_social_base_url(model)
            if base_url is None:
                return
            _set_social_status(model, "Publishing...")
            payload = {"text": text, "ts": int(time.time())}
            try:
                social.publish_social_event(
                    base_url,
                    identity=model.identity,
                    kind="post",
                    payload=payload,
                    prev_hash=model.social_prev_hash,
                )
            except Exception as exc:
                _set_social_status(model, f"Error: {exc}")
                return
            model.social_compose_text = ""
            model.social_compose_active = False
            _refresh_social()

        def _set_presence_status(text: str) -> None:
            model.set_presence_status(text)

        def _execute_presence_prompt(action: str, user_id: str) -> None:
            if not user_id:
                _set_presence_status("User id is required.")
                return
            if session_state is None:
                _set_presence_status("No active session. Press r to resume.")
                return
            base_url = session_state.base_url
            token = session_state.session_token
            try:
                if action == "watch":
                    _presence_watch(base_url, token, [user_id])
                    model.ensure_presence_contact(user_id)
                    _set_presence_status(f"Watching {user_id}.")
                elif action == "unwatch":
                    _presence_unwatch(base_url, token, [user_id])
                    model.remove_presence_contact(user_id)
                    _set_presence_status(f"Unwatched {user_id}.")
                elif action == "block":
                    response = _presence_block(base_url, token, [user_id])
                    blocked = response.get("blocked")
                    _set_presence_status(f"Blocked {user_id} (blocked={blocked}).")
                elif action == "unblock":
                    response = _presence_unblock(base_url, token, [user_id])
                    blocked = response.get("blocked")
                    _set_presence_status(f"Unblocked {user_id} (blocked={blocked}).")
                else:
                    _set_presence_status(f"Unknown presence action {action}.")
            except Exception as exc:
                _set_presence_status(f"Presence request failed: {exc}")

        def _expire_presence_entries() -> None:
            now_ms = int(time.time() * 1000)
            for entry in list(model.presence_entries.values()):
                expires_at = entry.get("expires_at")
                if isinstance(expires_at, int) and expires_at < now_ms:
                    entry["status"] = "offline"

        def _tick_presence() -> None:
            nonlocal presence_lease_expires_at, presence_last_lease_attempt
            _ensure_presence_thread()
            if not model.presence_enabled or session_state is None:
                presence_lease_expires_at = None
                return
            now = time.time()
            if now - presence_last_lease_attempt < 1.0:
                return
            now_ms = int(now * 1000)
            if presence_lease_expires_at is None or now_ms >= presence_lease_expires_at - (presence_renew_margin_seconds * 1000):
                presence_last_lease_attempt = now
                try:
                    if presence_lease_expires_at is None:
                        presence_lease_expires_at = _presence_lease(
                            session_state.base_url,
                            session_state.session_token,
                            model.identity.device_id,
                            presence_ttl_seconds,
                            model.presence_invisible,
                        )
                        _set_presence_status("Presence lease acquired.")
                    else:
                        presence_lease_expires_at = _presence_renew(
                            session_state.base_url,
                            session_state.session_token,
                            model.identity.device_id,
                            presence_ttl_seconds,
                            model.presence_invisible,
                        )
                        _set_presence_status("Presence lease renewed.")
                except Exception as exc:
                    _set_presence_status(f"Presence lease failed: {exc}")

        while True:
            # Rendering can occasionally fail during terminal resize. Keep the
            # event loop running and redraw on the next iteration.
            try:
                _drain_events()
                _expire_presence_entries()
                _tick_presence()
                draw_screen(stdscr, model)
            except curses.error:
                pass

            key = stdscr.getch()

            # Robust paste handling:
            # - Drain any immediately-available pending input so large pastes
            #   become one logical edit.
            # - Strip bracketed-paste markers and (for blob fields) whitespace
            #   so users can copy wrapped text and paste it back safely.
            state = model.render()
            focus = state.focus_area
            social_paste = focus == "social" and state.social_compose_active
            presence_paste = focus == "presence" and state.presence_prompt_active
            if (
                focus in {"fields", "compose", "new_dm"}
                or social_paste
                or presence_paste
            ) and (key == 27 or 0 <= key < 256) and key != 9:
                pending = _drain_pending_input(stdscr)
                # If we saw a lone ESC, briefly wait for a follow-on sequence
                # (common for bracketed paste start ...).
                if key == 27 and not pending:
                    stdscr.timeout(20)
                    try:
                        nxt = stdscr.getch()
                    finally:
                        stdscr.timeout(-1)
                    if nxt != -1:
                        pending = [nxt] + _drain_pending_input(stdscr)
                raw_codes = [key] + pending
                raw_text = "".join(chr(c) for c in raw_codes if 0 <= c < 256)

                if key == 27 and not pending and not social_paste:
                    # Bare ESC with nothing following.
                    continue

                if raw_text and (len(raw_text) > 1 or "\x1b" in raw_text or "\n" in raw_text or "\r" in raw_text):
                    if focus == "fields":
                        field_key = state.field_order[state.active_field]
                        strip_ws = field_key in _BLOB_FIELDS or field_key in _FULL_PREVIEW_FIELDS
                        cleaned = _sanitize_paste(raw_text, strip_all_whitespace=strip_ws, base64_only=(field_key in _BASE64_FIELDS))
                        if not strip_ws:
                            cleaned = cleaned.replace("\n", "").replace("\r", "")
                        if cleaned:
                            model.append_to_active_field(cleaned)
                        continue

                    if focus == "compose":
                        cleaned = _sanitize_paste(raw_text, strip_all_whitespace=False)
                        cleaned = cleaned.replace("\n", "").replace("\r", "")
                        if cleaned:
                            model.append_to_compose(cleaned)
                        continue
                    if focus == "new_dm":
                        cleaned = _sanitize_paste(raw_text, strip_all_whitespace=False)
                        cleaned = cleaned.replace("\n", "").replace("\r", "")
                        if cleaned:
                            field_key = state.new_dm_field_order[state.new_dm_active_field]
                            model.new_dm_fields[field_key] += cleaned
                        continue
                    if social_paste:
                        cleaned = _sanitize_paste(raw_text, strip_all_whitespace=False)
                        cleaned = cleaned.replace("\n", "").replace("\r", "")
                        if cleaned:
                            model.social_compose_text += cleaned
                        continue
                    if presence_paste:
                        cleaned = _sanitize_paste(raw_text, strip_all_whitespace=False)
                        cleaned = cleaned.replace("\n", "").replace("\r", "")
                        if cleaned:
                            model.presence_prompt_text += cleaned
                        continue

            normalized, char = _normalize_key(key)
            action = model.handle_key(normalized, char)
            if action == "quit":
                break
            if action == "toggle_mode":
                if model.render().mode == MODE_HARNESS:
                    _stop_tail_threads()
                else:
                    _ensure_tail_threads()
                    _ensure_presence_thread()
            if action == "panel_toggle":
                if model.presence_active and not model.presence_enabled:
                    model.presence_enabled = True
                if model.presence_active:
                    _set_presence_status("Presence panel active.")
                else:
                    _set_presence_status("")
                _ensure_presence_thread()
            if action == "new_conv":
                fields = model.render().fields
                if not fields.get("dm_name") or not fields.get("dm_state_dir"):
                    model.append_transcript(
                        "sys",
                        "Set dm_name and dm_state_dir in Parameters before creating a new DM.",
                    )
                else:
                    model.add_conv(fields.get("dm_name", ""), fields.get("dm_state_dir", ""))
                    model.append_transcript("sys", f"Added conversation {fields.get('dm_name', '')}.")
            if action == "run":
                _run_action(model, lambda lines: [model.append_transcript("sys", line) for line in lines])
            if action == "resume":
                session_state = _resume_or_start_session(model)
                _stop_tail_threads()
                _ensure_tail_threads()
            if action == "social_toggle":
                if model.social_active:
                    _set_social_status(model, "Social panel active.")
                else:
                    _set_social_status(model, "")
            if action in {"social_target_self", "social_target_peer"}:
                if action == "social_target_peer":
                    peer_user_id = str(model.get_selected_conv().get("peer_user_id", "")).strip()
                    if not peer_user_id:
                        model.social_target = "self"
                        _append_system_message(model, "Selected conversation has no peer_user_id.")
                        _set_social_status(model, "No peer_user_id found; staying on self.")
                        continue
                model.social_items = []
                model.social_prev_hash = None
                model.social_scroll = 0
                model.social_selected_idx = 0
                target_label = "self" if model.social_target == "self" else "peer"
                _set_social_status(model, f"Target set to {target_label}. Press r to refresh.")
            if action == "social_refresh":
                _refresh_social()
            if action == "social_publish":
                _publish_social()
            if action == "create_dm":
                new_dm = model.render().new_dm_fields
                _create_new_dm(
                    model,
                    session_state,
                    runtime_state,
                    new_dm.get("peer_user_id", "").strip(),
                    new_dm.get("name", "").strip(),
                    new_dm.get("state_dir", "").strip(),
                    new_dm.get("conv_id", "").strip(),
                )
                model.new_dm_active = False
                model.focus_area = "conversations"
                _ensure_tail_threads()
            if action == "send":
                compose_text = model.compose_text.strip("\n")
                if not compose_text:
                    model.append_transcript("sys", "Compose buffer is empty.")
                    continue
                if model.render().mode == MODE_HARNESS:
                    _run_dm_encrypt(model, lambda lines: [model.append_transcript("sys", line) for line in lines], compose_text)
                else:
                    _send_dm_message(model, session_state, runtime_state, compose_text)
                model.compose_text = ""
            if action == "presence_prompt_submit":
                action_name = model.presence_prompt_action
                prompt_text = model.presence_prompt_text.strip()
                model.presence_prompt_active = False
                model.presence_prompt_text = ""
                model.presence_prompt_action = ""
                _execute_presence_prompt(action_name, prompt_text)
            if action == "presence_toggle_invisible":
                _set_presence_status("Invisible mode toggled.")
                presence_lease_expires_at = None
            if action == "presence_toggle_enabled":
                label = "enabled" if model.presence_enabled else "disabled"
                _set_presence_status(f"Presence {label}.")
                presence_lease_expires_at = None
                _ensure_presence_thread()

        _stop_tail_threads()
        _stop_presence_thread()

    curses.wrapper(_runner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
