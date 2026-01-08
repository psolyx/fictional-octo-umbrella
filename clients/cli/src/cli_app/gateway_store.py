"""Persist gateway session tokens and cursors for the CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

BASE_DIR = Path.home() / ".polycentric_demo"
SESSION_PATH = BASE_DIR / "gateway_session.json"
CURSORS_PATH = BASE_DIR / "gateway_cursors.json"


def _atomic_write_json(path: Path, payload: Dict[str, object]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, indent=2, sort_keys=True)

    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def load_session(path: Path = SESSION_PATH) -> Optional[Dict[str, str]]:
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    try:
        return {
            "base_url": str(data["base_url"]),
            "session_token": str(data["session_token"]),
            "resume_token": str(data["resume_token"]),
        }
    except KeyError:
        return None


def save_session(base_url: str, session_token: str, resume_token: str, path: Path = SESSION_PATH) -> None:
    _atomic_write_json(
        path,
        {
            "base_url": base_url,
            "session_token": session_token,
            "resume_token": resume_token,
        },
    )


def load_cursors(path: Path = CURSORS_PATH) -> Dict[str, int]:
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}
    parsed: Dict[str, int] = {}
    for key, value in data.items():
        try:
            parsed[str(key)] = int(value)
        except (ValueError, TypeError):
            continue
    return parsed


def save_cursors(cursors: Dict[str, int], path: Path = CURSORS_PATH) -> None:
    payload = {conv_id: int(seq) for conv_id, seq in cursors.items()}
    _atomic_write_json(path, payload)


def get_next_seq(conv_id: str, path: Path = CURSORS_PATH) -> int:
    return max(load_cursors(path).get(conv_id, 1), 1)


def update_next_seq(conv_id: str, acked_seq: int, path: Path = CURSORS_PATH) -> int:
    cursors = load_cursors(path)
    current = cursors.get(conv_id, 1)
    next_seq = max(current, acked_seq + 1, 1)
    cursors[conv_id] = next_seq
    save_cursors(cursors, path)
    return next_seq
