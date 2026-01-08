import importlib
from pathlib import Path


def _reload_profile_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from cli_app import profile_paths

    return importlib.reload(profile_paths)


def test_default_profile_paths_legacy(monkeypatch, tmp_path):
    profile_paths = _reload_profile_paths(tmp_path, monkeypatch)

    paths = profile_paths.resolve_profile_paths("default")

    base_dir = tmp_path / ".polycentric_demo"
    assert paths.identity_path == base_dir / "identity.json"
    assert paths.session_path == base_dir / "gateway_session.json"
    assert paths.cursors_path == base_dir / "gateway_cursors.json"
    assert paths.identity_path.parent.is_dir()
    assert (paths.identity_path.parent.stat().st_mode & 0o777) == 0o700


def test_named_profile_paths(monkeypatch, tmp_path):
    profile_paths = _reload_profile_paths(tmp_path, monkeypatch)

    paths = profile_paths.resolve_profile_paths("u1d1")

    profile_dir = tmp_path / ".polycentric_demo" / "profiles" / "u1d1"
    assert paths.identity_path == profile_dir / "identity.json"
    assert paths.session_path == profile_dir / "gateway_session.json"
    assert paths.cursors_path == profile_dir / "gateway_cursors.json"
    assert profile_dir.is_dir()
    assert (profile_dir.stat().st_mode & 0o777) == 0o700
