import json
from pathlib import Path

from cli_app import identity_store


def test_load_or_create_identity_is_stable(tmp_path: Path):
    identity_path = tmp_path / "identity.json"
    first = identity_store.load_or_create_identity(identity_path)
    second = identity_store.load_or_create_identity(identity_path)

    assert identity_path.exists()
    assert first == second
    assert first.user_id == second.user_id


def test_rotate_device_changes_device_fields(tmp_path: Path):
    identity_path = tmp_path / "identity.json"
    original = identity_store.load_or_create_identity(identity_path)
    rotated = identity_store.rotate_device(identity_path)

    assert rotated.auth_token == original.auth_token
    assert rotated.user_id == original.user_id
    assert rotated.device_id != original.device_id
    assert rotated.device_credential != original.device_credential

    reloaded = identity_store.load_or_create_identity(identity_path)
    assert reloaded.device_id == rotated.device_id


def test_identity_written_atomically(tmp_path: Path):
    identity_path = tmp_path / "identity.json"
    record = identity_store.load_or_create_identity(identity_path)

    assert identity_path.exists()
    with identity_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["auth_token"] == record.auth_token
    assert "device_id" in data
    assert "device_credential" in data
    assert not identity_path.with_suffix(identity_path.suffix + ".tmp").exists()
