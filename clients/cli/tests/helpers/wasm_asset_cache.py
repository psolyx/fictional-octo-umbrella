import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Iterable, Optional


_LOCK_NAME = ".wasm_asset_cache_lock"
_META_NAME = "wasm_asset_cache.json"


class _CacheLock:
    def __init__(self, cache_dir: Path, *, timeout_s: float = 30.0) -> None:
        self._lock_dir = cache_dir / _LOCK_NAME
        self._timeout_s = timeout_s

    def __enter__(self) -> None:
        deadline = time.time() + self._timeout_s
        while True:
            try:
                os.mkdir(self._lock_dir)
                return
            except FileExistsError:
                if time.time() >= deadline:
                    raise AssertionError(
                        f"Timed out waiting for cache lock: {self._lock_dir}"
                    ) from None
                time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            os.rmdir(self._lock_dir)
        except FileNotFoundError:
            return


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _iter_inputs(tools_dir: Path, build_script: Path) -> Iterable[Path]:
    yield build_script
    for candidate in ("go.mod", "go.sum"):
        path = tools_dir / candidate
        if path.exists():
            yield path
    for directory in ("cmd", "internal", "vendor"):
        root = tools_dir / directory
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield path


def _collect_input_manifest(tools_dir: Path, build_script: Path) -> list[dict]:
    manifest: list[dict] = []
    for path in _iter_inputs(tools_dir, build_script):
        rel = path.relative_to(tools_dir)
        stat = path.stat()
        manifest.append(
            {
                "path": str(rel),
                "sha256": _hash_file(path),
                "size": stat.st_size,
            }
        )
    return manifest


def _get_go_info() -> Optional[dict]:
    if not shutil.which("go"):
        return None
    goversion = subprocess.check_output(
        ["go", "env", "GOVERSION"],
        text=True,
    ).strip()
    goroot = subprocess.check_output(
        ["go", "env", "GOROOT"],
        text=True,
    ).strip()
    return {
        "go_version": goversion,
        "go_root": goroot,
    }


def _cache_context(go_info: dict) -> dict:
    return {
        "go_version": go_info.get("go_version"),
        "go_root": go_info.get("go_root"),
        "goflags": os.environ.get("GOFLAGS", ""),
        "gotoolchain": os.environ.get("GOTOOLCHAIN", ""),
        "goos": "js",
        "goarch": "wasm",
    }


def _compute_cache_key(
    *, tools_dir: Path, build_script: Path, go_info: dict, manifest: list[dict]
) -> str:
    hasher = hashlib.sha256()
    context = _cache_context(go_info)
    for key in sorted(context.keys()):
        hasher.update(f"{key}={context[key]}".encode("utf-8"))
    for entry in manifest:
        hasher.update(entry["path"].encode("utf-8"))
        hasher.update(entry["sha256"].encode("utf-8"))
    return hasher.hexdigest()


def _load_metadata(metadata_path: Path) -> dict:
    if not metadata_path.exists():
        return {}
    with metadata_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _metadata_matches(metadata: dict, cache_key: str) -> bool:
    if metadata.get("cache_key") != cache_key:
        return False
    if not isinstance(metadata.get("wasm_exec"), dict):
        return False
    if not isinstance(metadata.get("wasm"), dict):
        return False
    return True


def _extract_expected_hashes(metadata: dict) -> tuple[Optional[str], Optional[str]]:
    exec_hash = metadata.get("wasm_exec", {}).get("sha256")
    wasm_hash = metadata.get("wasm", {}).get("sha256")
    if not isinstance(exec_hash, str) or not isinstance(wasm_hash, str):
        return None, None
    return exec_hash, wasm_hash


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f"{path.name}.",
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(handle.name, path)


def _atomic_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=str(dest.parent),
        prefix=f"{dest.name}.",
        suffix=".tmp",
    ) as handle:
        temp_path = Path(handle.name)
    shutil.copy2(src, temp_path)
    os.replace(temp_path, dest)


def _validate_asset(asset_path: Path, expected_hash: str) -> bool:
    return asset_path.exists() and _hash_file(asset_path) == expected_hash


def _ensure_cache_dir(cache_dir: Path) -> None:
    if cache_dir.exists() and not cache_dir.is_dir():
        raise AssertionError(f"Cache dir is not a directory: {cache_dir}")
    cache_dir.mkdir(parents=True, exist_ok=True)


def _assert_tools_layout(tools_dir: Path, build_script: Path) -> None:
    if not tools_dir.exists():
        raise AssertionError(f"WASM tools dir missing: {tools_dir}")
    if not build_script.exists():
        raise AssertionError(f"WASM build script missing: {build_script}")
    go_mod = tools_dir / "go.mod"
    if not go_mod.exists():
        raise AssertionError(f"WASM go.mod missing: {go_mod}")
    wasm_cmd_dir = tools_dir / "cmd"
    if not wasm_cmd_dir.exists():
        raise AssertionError(f"WASM cmd dir missing: {wasm_cmd_dir}")


def _record_metadata(
    *,
    metadata_path: Path,
    cache_key: str,
    go_info: dict,
    manifest: list[dict],
    exec_hash: str,
    wasm_hash: str,
) -> None:
    _atomic_write_json(
        metadata_path,
        {
            "cache_key": cache_key,
            "cache_context": _cache_context(go_info),
            "go_info": go_info,
            "input_manifest": manifest,
            "wasm_exec": {"sha256": exec_hash},
            "wasm": {"sha256": wasm_hash},
        },
    )


def _build_wasm_assets(build_script: Path, tools_dir: Path) -> None:
    subprocess.run(["bash", str(build_script)], cwd=str(tools_dir), check=True)


def ensure_wasm_assets(
    *,
    wasm_exec_path: Path,
    wasm_path: Path,
    tools_dir: Path,
    cache_dir: Path,
) -> None:
    """Ensure WASM assets exist and are cached for deterministic reuse.

    This function is safe to call from parallel test workers; a simple
    directory lock prevents concurrent rebuilds while allowing cache hits
    to short-circuit quickly. Cache keys incorporate Go toolchain metadata,
    pinned build args, and a manifest of the harness inputs.
    """
    build_script = tools_dir / "build_wasm.sh"
    _assert_tools_layout(tools_dir, build_script)

    _ensure_cache_dir(cache_dir)
    metadata_path = cache_dir / _META_NAME
    metadata = _load_metadata(metadata_path)
    go_info = _get_go_info()
    if go_info is None:
        cached_go_info = metadata.get("go_info")
        if isinstance(cached_go_info, dict):
            go_info = cached_go_info
        else:
            go_info = {"go_version": "missing", "go_root": "missing"}

    manifest = _collect_input_manifest(tools_dir, build_script)
    cache_key = _compute_cache_key(
        tools_dir=tools_dir,
        build_script=build_script,
        go_info=go_info,
        manifest=manifest,
    )
    artifacts_dir = cache_dir / "artifacts" / cache_key
    cached_wasm_exec = artifacts_dir / wasm_exec_path.name
    cached_wasm = artifacts_dir / wasm_path.name

    with _CacheLock(cache_dir):
        metadata = _load_metadata(metadata_path)
        if _metadata_matches(metadata, cache_key):
            exec_hash, wasm_hash = _extract_expected_hashes(metadata)
            if exec_hash and wasm_hash:
                if _validate_asset(wasm_exec_path, exec_hash) and _validate_asset(
                    wasm_path, wasm_hash
                ):
                    return
                if _validate_asset(cached_wasm_exec, exec_hash) and _validate_asset(
                    cached_wasm, wasm_hash
                ):
                    _atomic_copy(cached_wasm_exec, wasm_exec_path)
                    _atomic_copy(cached_wasm, wasm_path)
                    return

        if not shutil.which("go"):
            raise unittest.SkipTest("Go toolchain not available for WASM build")

        _build_wasm_assets(build_script, tools_dir)
        if not wasm_exec_path.exists():
            raise AssertionError(
                "WASM build completed but wasm_exec.js is missing"
            )
        if not wasm_path.exists():
            raise AssertionError(
                "WASM build completed but mls_harness.wasm is missing"
            )

        exec_hash = _hash_file(wasm_exec_path)
        wasm_hash = _hash_file(wasm_path)
        _atomic_copy(wasm_exec_path, cached_wasm_exec)
        _atomic_copy(wasm_path, cached_wasm)
        _record_metadata(
            metadata_path=metadata_path,
            cache_key=cache_key,
            go_info=go_info,
            manifest=manifest,
            exec_hash=exec_hash,
            wasm_hash=wasm_hash,
        )
