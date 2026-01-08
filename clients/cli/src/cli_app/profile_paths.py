"""Resolve per-profile CLI storage paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cli_app import gateway_store, identity_store

BASE_DIR = Path.home() / ".polycentric_demo"
PROFILES_DIR = BASE_DIR / "profiles"


@dataclass(frozen=True)
class ProfilePaths:
    identity_path: Path
    session_path: Path
    cursors_path: Path


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


def resolve_profile_paths(profile: str) -> ProfilePaths:
    if profile == "default":
        identity_path = identity_store.DEFAULT_IDENTITY_PATH
        session_path = gateway_store.SESSION_PATH
        cursors_path = gateway_store.CURSORS_PATH
        _ensure_private_dir(identity_path.parent)
        _ensure_private_dir(session_path.parent)
        _ensure_private_dir(cursors_path.parent)
        return ProfilePaths(
            identity_path=identity_path,
            session_path=session_path,
            cursors_path=cursors_path,
        )

    profile_dir = PROFILES_DIR / profile
    _ensure_private_dir(profile_dir)
    return ProfilePaths(
        identity_path=profile_dir / "identity.json",
        session_path=profile_dir / "gateway_session.json",
        cursors_path=profile_dir / "gateway_cursors.json",
    )
