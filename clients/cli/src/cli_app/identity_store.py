"""Offline identity and device provisioning for the CLI/TUI."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cli_app import polycentric_ed25519

DEFAULT_IDENTITY_PATH = Path.home() / ".polycentric_demo" / "identity.json"


@dataclass(frozen=True)
class IdentityRecord:
    auth_token: str
    user_id: str
    device_id: str
    device_credential: str
    seed_b64: str
    pub_key_b64: str



def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _derive_user_id(auth_token: str) -> str:
    if auth_token.startswith("Bearer "):
        return auth_token[len("Bearer ") :]
    return auth_token


def _derive_seed_from_auth(auth_token: str) -> str:
    digest = hashlib.sha256(auth_token.encode("utf-8")).digest()
    return _b64url(digest[:32])


def _generate_identity() -> IdentityRecord:
    auth_token = f"Bearer pc_sys_{_b64url(secrets.token_bytes(32))}"
    device_id = f"d_{_b64url(secrets.token_bytes(16))}"
    device_credential = _b64url(secrets.token_bytes(32))

    seed_payload = polycentric_ed25519.generate()
    user_id = seed_payload["user_id"]
    seed_b64 = seed_payload["seed_b64"]
    pub_key_b64 = seed_payload["pub_key_b64"]

    return IdentityRecord(
        auth_token=auth_token,
        user_id=user_id,
        device_id=device_id,
        device_credential=device_credential,
        seed_b64=seed_b64,
        pub_key_b64=pub_key_b64,
    )


def _atomic_write_json(path: Path, record: IdentityRecord) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(record.__dict__, indent=2, sort_keys=True)

    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _load_identity(path: Path) -> IdentityRecord:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("identity payload must be a JSON object")

    auth_token = str(data["auth_token"])
    user_id = str(data.get("user_id") or _derive_user_id(auth_token))
    device_id = str(data["device_id"])
    device_credential = str(data["device_credential"])
    seed_b64 = str(data.get("seed_b64") or _derive_seed_from_auth(auth_token))
    pub_meta = polycentric_ed25519.derive_pubkey(seed_b64)
    pub_key_b64 = str(data.get("pub_key_b64") or pub_meta["pub_key_b64"])

    derived_user_id = pub_meta["user_id"]
    if not user_id:
        user_id = derived_user_id
    elif user_id != derived_user_id:
        user_id = derived_user_id

    return IdentityRecord(
        auth_token=auth_token,
        user_id=user_id,
        device_id=device_id,
        device_credential=device_credential,
        seed_b64=seed_b64,
        pub_key_b64=pub_key_b64,
    )


def load_or_create_identity(path: Path | str = DEFAULT_IDENTITY_PATH) -> IdentityRecord:
    target_path = Path(path).expanduser()
    try:
        record = _load_identity(target_path)
        _atomic_write_json(target_path, record)
        return record
    except FileNotFoundError:
        record = _generate_identity()
        _atomic_write_json(target_path, record)
        return record
    except (ValueError, KeyError, json.JSONDecodeError):
        record = _generate_identity()
        _atomic_write_json(target_path, record)
        return record


def rotate_device(path: Path | str = DEFAULT_IDENTITY_PATH) -> IdentityRecord:
    current = load_or_create_identity(path)
    updated = IdentityRecord(
        auth_token=current.auth_token,
        user_id=current.user_id,
        device_id=f"d_{_b64url(secrets.token_bytes(16))}",
        device_credential=_b64url(secrets.token_bytes(32)),
        seed_b64=current.seed_b64,
        pub_key_b64=current.pub_key_b64,
    )
    _atomic_write_json(Path(path).expanduser(), updated)
    return updated
