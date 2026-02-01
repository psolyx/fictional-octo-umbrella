"""Curses-based TUI wrapper for the MLS harness CLI POC."""

from __future__ import annotations

import curses
import io
import json
import re
import sys
from types import SimpleNamespace
from typing import Callable, Dict, Iterable

from cli_app import identity_store

from cli_app import mls_poc
from cli_app.tui_model import DEFAULT_SETTINGS_FILE, TuiModel, load_settings


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
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    left_width = min(40, max(24, max_x // 3))
    right_start = left_width + 1
    header_offset = 6
    compose_height = 3
    transcript_height = max(3, max_y - header_offset - compose_height - 1)

    render = model.render()

    _render_text(stdscr, 0, 1, "Phase 0.5 MLS harness TUI")
    _render_text(stdscr, 1, 1, "Tab: focus | Enter: run | q: quit | n: new DM")
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

    stdscr.refresh()


def _visible_transcript(entries: Iterable[Dict[str, str]], height: int, scroll: int) -> list[Dict[str, str]]:
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


def _blob_preview_lines(label: str, value: str, chunk: int = 64) -> list[str]:
    """Render a copy-friendly blob preview across multiple transcript lines."""

    header = f"{label} (len={len(value)}):"
    return [header] + _wrap_chunks(value, chunk)


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

        while True:
            # Rendering can occasionally fail during terminal resize. Keep the
            # event loop running and redraw on the next iteration.
            try:
                draw_screen(stdscr, model)
            except curses.error:
                pass

            key = stdscr.getch()

            # Robust paste handling:
            # - Drain any immediately-available pending input so large pastes
            #   become one logical edit.
            # - Strip bracketed-paste markers and (for blob fields) whitespace
            #   so users can copy wrapped text and paste it back safely.
            focus = model.render().focus_area
            if focus in {"fields", "compose"} and (key == 27 or 0 <= key < 256) and key != 9:
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

                if key == 27 and not pending:
                    # Bare ESC with nothing following.
                    continue

                if raw_text and (len(raw_text) > 1 or "\x1b" in raw_text or "\n" in raw_text or "\r" in raw_text):
                    if focus == "fields":
                        state = model.render()
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

            normalized, char = _normalize_key(key)
            action = model.handle_key(normalized, char)
            if action == "quit":
                break
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
            if action == "send":
                compose_text = model.compose_text.strip("\n")
                if compose_text:
                    _run_dm_encrypt(model, lambda lines: [model.append_transcript("sys", line) for line in lines], compose_text)
                    model.compose_text = ""
                else:
                    model.append_transcript("sys", "Compose buffer is empty.")

    curses.wrapper(_runner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
