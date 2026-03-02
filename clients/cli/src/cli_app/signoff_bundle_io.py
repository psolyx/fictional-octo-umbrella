from __future__ import annotations

import gzip
import hashlib
import tarfile
from pathlib import Path
from pathlib import PurePosixPath


def sha256_file(path: Path) -> str:
    """Return a lowercase sha256 hex digest for *path* using deterministic chunking."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def iter_bundle_files(root: Path, *, exclude_relpaths: set[str]) -> list[Path]:
    """Return sorted bundle file paths by relative POSIX path, excluding requested relpaths."""
    files: list[tuple[str, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in exclude_relpaths:
            continue
        files.append((rel, path))
    files.sort(key=lambda item: item[0])
    return [path for _, path in files]


def write_sha256_manifest(
    root: Path,
    *,
    manifest_name: str = "sha256.txt",
    exclude_relpaths: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Write a deterministic sorted sha256 manifest and return ``[(relpath, digest), ...]``."""
    excludes = set(exclude_relpaths or {manifest_name})
    entries: list[tuple[str, str]] = []
    for path in iter_bundle_files(root, exclude_relpaths=excludes):
        rel = path.relative_to(root).as_posix()
        entries.append((rel, sha256_file(path)))

    manifest_path = root / manifest_name
    with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
        for rel, digest in entries:
            handle.write(f"{digest}  {rel}\n")
    return entries


def parse_sha256_manifest(text: str) -> list[tuple[str, str]]:
    """Parse and validate strict deterministic sha256 manifest lines.

    Rules: no blank lines, `<64hex>  <relpath>` format, sorted relpaths, no duplicates.
    """
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if not line.strip():
            raise ValueError("sha256_blank_line")
        digest, sep, relpath = line.partition("  ")
        if sep != "  " or not relpath:
            raise ValueError("sha256_format_invalid")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"sha256_digest_invalid file={relpath}")
        if relpath in seen:
            raise ValueError(f"sha256_duplicate_file file={relpath}")
        seen.add(relpath)
        entries.append((relpath, digest))

    relpaths = [rel for rel, _ in entries]
    if relpaths != sorted(relpaths):
        raise ValueError("sha256_not_sorted")
    return entries


def verify_sha256_manifest(
    root: Path,
    *,
    manifest_name: str = "sha256.txt",
    exclude_relpaths: set[str] | None = None,
) -> None:
    """Verify deterministic sha256 manifest file-set and digests for a bundle root."""
    excludes = set(exclude_relpaths or {manifest_name})
    manifest_path = root / manifest_name
    entries = parse_sha256_manifest(manifest_path.read_text(encoding="utf-8"))
    relpaths = [rel for rel, _ in entries]

    expected_files = iter_bundle_files(root, exclude_relpaths=excludes)
    expected_relpaths = [path.relative_to(root).as_posix() for path in expected_files]
    if relpaths != expected_relpaths:
        raise ValueError("sha256_file_set_mismatch")

    for relpath, digest in entries:
        full_path = root / relpath
        if not full_path.is_file():
            raise ValueError(f"sha256_referenced_missing file={relpath}")
        actual = sha256_file(full_path)
        if actual != digest:
            raise ValueError(f"sha256_mismatch file={relpath}")


def build_deterministic_tgz(bundle_dir: Path, *, out_dir: Path | None = None) -> tuple[Path, Path]:
    """Build deterministic `<bundle>.tgz` + `<bundle>.tgz.sha256` with normalized tar+gzip metadata."""
    target_dir = out_dir if out_dir is not None else bundle_dir.parent
    archive_path = target_dir / f"{bundle_dir.name}.tgz"
    archive_sha_path = target_dir / f"{bundle_dir.name}.tgz.sha256"

    rel_dirs = sorted(path.relative_to(bundle_dir).as_posix() for path in bundle_dir.rglob("*") if path.is_dir())
    rel_files = sorted(path.relative_to(bundle_dir).as_posix() for path in bundle_dir.rglob("*") if path.is_file())

    with archive_path.open("wb") as archive_handle:
        with gzip.GzipFile(fileobj=archive_handle, mode="wb", mtime=0) as gzip_handle:
            with tarfile.open(fileobj=gzip_handle, mode="w|") as tar_handle:
                members: list[tuple[str, Path, bool]] = [(bundle_dir.name, bundle_dir, True)]
                for rel_dir in rel_dirs:
                    members.append((f"{bundle_dir.name}/{rel_dir}", bundle_dir / rel_dir, True))
                for rel_file in rel_files:
                    members.append((f"{bundle_dir.name}/{rel_file}", bundle_dir / rel_file, False))

                for member_name, source_path, is_dir in members:
                    info = tarfile.TarInfo(name=member_name)
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    if is_dir:
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o755
                        info.size = 0
                        tar_handle.addfile(info)
                        continue
                    info.mode = 0o644
                    info.size = source_path.stat().st_size
                    with source_path.open("rb") as file_handle:
                        tar_handle.addfile(info, fileobj=file_handle)

    archive_digest = sha256_file(archive_path)
    with archive_sha_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{archive_digest}  {archive_path.name}\n")
    return archive_path, archive_sha_path


def archive_basename(path: Path) -> str | None:
    """Return base archive name for .tgz/.tar.gz inputs, else None."""
    if path.name.endswith(".tgz"):
        return path.name[: -len(".tgz")]
    if path.name.endswith(".tar.gz"):
        return path.name[: -len(".tar.gz")]
    return None


def verify_archive_sha256(archive_path: Path) -> None:
    """Verify sibling `<archive>.sha256` one-line digest contract for the archive file."""
    digest_path = Path(f"{archive_path.as_posix()}.sha256")
    if not digest_path.is_file():
        raise ValueError("archive_sha256_missing")
    lines = digest_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ValueError("archive_sha256_format_invalid")
    digest, sep, filename = lines[0].partition("  ")
    if sep != "  " or not filename:
        raise ValueError("archive_sha256_format_invalid")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("archive_sha256_format_invalid")
    if filename != archive_path.name:
        raise ValueError("archive_sha256_name_mismatch")
    if sha256_file(archive_path) != digest:
        raise ValueError("archive_sha256_mismatch")


def safe_extract_tgz(archive_path: Path, *, temp_root: Path) -> Path:
    """Safely extract deterministic signoff archive after validating traversal + member types.

    Rejects absolute/member-parent traversal and links/devices/fifos before extraction.
    """
    archive_base = archive_basename(archive_path)
    if archive_base is None:
        raise ValueError("archive_extension_invalid")
    if not archive_path.is_file():
        raise ValueError("archive_missing")

    verify_archive_sha256(archive_path)

    with tarfile.open(str(archive_path), mode="r:gz") as tar_handle:
        members = tar_handle.getmembers()
        for member in members:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute():
                raise ValueError("archive_member_absolute")
            if ".." in member_path.parts:
                raise ValueError("archive_member_parent_ref")
            if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
                raise ValueError("archive_member_type_unsupported")
            target = (temp_root / Path(*member_path.parts)).resolve()
            if target != temp_root and temp_root not in target.parents:
                raise ValueError("archive_member_escape")
        tar_handle.extractall(path=temp_root, members=members)

    top_level = sorted(path for path in temp_root.iterdir())
    if len(top_level) != 1 or not top_level[0].is_dir():
        raise ValueError("archive_root_invalid")
    if top_level[0].name != archive_base:
        raise ValueError("archive_root_name_mismatch")
    return top_level[0]

