"""Deterministic static Phase 5.2 security + accessibility audit."""

from __future__ import annotations

from pathlib import Path
import re
from typing import TextIO

PHASE5_2_STATIC_AUDIT_BEGIN = "PHASE5_2_STATIC_AUDIT_BEGIN"
PHASE5_2_STATIC_AUDIT_OK = "PHASE5_2_STATIC_AUDIT_OK"
PHASE5_2_STATIC_AUDIT_END = "PHASE5_2_STATIC_AUDIT_END"

_CONSOLE_LOG_LITERAL_RE = re.compile(r"console\\.log\\s*\\(([^)]*)\\)", re.MULTILINE)
_STATUS_ASSIGN_LITERAL_RE = re.compile(
    r"(?:textContent|innerText|innerHTML)\\s*=\\s*([\"'])(?P<literal>(?:\\\\.|(?!\\1).)*)\\1",
    re.MULTILINE,
)
_TOKEN_LITERAL_RE = re.compile(r"\\b(?:st_|rt_)[A-Za-z0-9_-]*\\b")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _iter_web_js_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "clients" / "web").glob("*.js"))


def _find_forbidden_web_literals(repo_root: Path) -> tuple[Path, str] | None:
    for path in _iter_web_js_files(repo_root):
        text = _read_text(path)
        for match in _CONSOLE_LOG_LITERAL_RE.finditer(text):
            if _TOKEN_LITERAL_RE.search(match.group(1) or ""):
                return path, "token-like literal in console.log context"
        for match in _STATUS_ASSIGN_LITERAL_RE.finditer(text):
            literal = match.group("literal")
            if _TOKEN_LITERAL_RE.search(literal):
                return path, "token-like literal in status assignment context"
    return None


def _contains_all(path: Path, markers: tuple[str, ...]) -> bool:
    text = _read_text(path)
    return all(marker in text for marker in markers)


def run_audit(repo_root: str, *, out: TextIO) -> int:
    root = Path(repo_root).resolve()
    checks: list[tuple[str, bool, str | None, str | None]] = []

    forbidden = _find_forbidden_web_literals(root)
    if forbidden:
        bad_path, reason = forbidden
        checks.append(
            (
                "web_secret_redaction_literals",
                False,
                reason,
                str(bad_path.relative_to(root)).replace("\\", "/"),
            )
        )
    else:
        checks.append(("web_secret_redaction_literals", True, "ok", "clients/web/*.js"))

    tui_path = root / "clients" / "cli" / "src" / "cli_app" / "tui_app.py"
    tui_markers = (
        "from cli_app.redact import redact_text",
        "model.social_status_line = redact_text(text)",
        "_append_system_message(model",
    )
    checks.append(
        (
            "tui_secret_redaction_hooks",
            _contains_all(tui_path, tui_markers),
            "missing redact_text marker in tui status output path",
            "clients/cli/src/cli_app/tui_app.py",
        )
    )

    ws_transport_path = root / "gateway" / "src" / "gateway" / "ws_transport.py"
    ws_401_markers = ("WWW-Authenticate", "Bearer", "_with_no_store(response)")
    checks.append(
        (
            "gateway_401_www_auth_no_store",
            _contains_all(ws_transport_path, ws_401_markers),
            "missing 401 marker (WWW-Authenticate/Bearer/no-store)",
            "gateway/src/gateway/ws_transport.py",
        )
    )

    ws_429_markers = ("Retry-After", "retry_after_s")
    web_retry_markers = ("Retry-After", "retry_after_s", "parse_retry_after_s")
    checks.append(
        (
            "retry_after_429_posture",
            _contains_all(ws_transport_path, ws_429_markers)
            and _contains_all(root / "clients" / "web" / "gateway_ws_client.js", web_retry_markers),
            "missing retry-after markers in gateway/web client",
            "gateway/src/gateway/ws_transport.py",
        )
    )

    checks.append(
        (
            "web_focus_visible_posture",
            _contains_all(root / "clients" / "web" / "styles.css", (":focus-visible",)),
            "missing :focus-visible marker",
            "clients/web/styles.css",
        )
    )

    index_html = root / "clients" / "web" / "index.html"
    a11y_live_markers = (
        'id="session_expired_banner"',
        'id="replay_window_banner"',
        'id="conv_filter_status"',
        'role="status"',
        'aria-live="polite"',
    )
    checks.append(
        (
            "web_live_region_status_markers",
            _contains_all(index_html, a11y_live_markers),
            "missing required role=status aria-live markers",
            "clients/web/index.html",
        )
    )

    roving_markers = ('data-roving-tabindex="true"', "setAttribute('tabindex', selected ? '0' : '-1')")
    checks.append(
        (
            "web_roving_tabindex_markers",
            _contains_all(root / "clients" / "web" / "gateway_ws_client.js", roving_markers),
            "missing roving tabindex markers",
            "clients/web/gateway_ws_client.js",
        )
    )

    help_markers = (
        "/: filter query",
        "o: unread-only filter",
        "i: pinned-only filter",
        "c: clear filter",
    )
    checks.append(
        (
            "tui_help_overlay_filter_keys",
            _contains_all(tui_path, help_markers),
            "missing filter key help overlay markers",
            "clients/cli/src/cli_app/tui_app.py",
        )
    )

    print(PHASE5_2_STATIC_AUDIT_BEGIN, file=out)
    failures = 0
    for index, (name, ok, reason, file_path) in enumerate(checks, start=1):
        if ok:
            print(f"check={index} ok {name} file={file_path}", file=out)
        else:
            failures += 1
            print(f"check={index} FAIL {name} reason={reason} file={file_path}", file=out)
    if failures == 0:
        print(PHASE5_2_STATIC_AUDIT_OK, file=out)
    print(PHASE5_2_STATIC_AUDIT_END, file=out)
    return 0 if failures == 0 else 2
