from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import TextIO

from cli_app.phase5_2_signoff_verify import verify_signoff_bundle

PHASE5_2_SIGNOFF_COMPARE_BEGIN = "PHASE5_2_SIGNOFF_COMPARE_BEGIN"
PHASE5_2_SIGNOFF_COMPARE_OK = "PHASE5_2_SIGNOFF_COMPARE_OK"
PHASE5_2_SIGNOFF_COMPARE_END = "PHASE5_2_SIGNOFF_COMPARE_END"
PHASE5_2_SIGNOFF_COMPARE_V1 = "PHASE5_2_SIGNOFF_COMPARE_V1"


class _CompareFailure(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _archive_basename(path: Path) -> str | None:
    if path.name.endswith(".tgz"):
        return path.name[: -len(".tgz")]
    if path.name.endswith(".tar.gz"):
        return path.name[: -len(".tar.gz")]
    return None


def _verify_archive_digest(archive: Path) -> None:
    digest_path = Path(f"{archive.as_posix()}.sha256")
    if not digest_path.is_file():
        raise _CompareFailure("compare_fail bundle_verify_failed")

    digest_lines = digest_path.read_text(encoding="utf-8").splitlines()
    if len(digest_lines) != 1:
        raise _CompareFailure("compare_fail bundle_verify_failed")
    match = re.fullmatch(r"([0-9a-f]{64})  (.+)", digest_lines[0])
    if match is None:
        raise _CompareFailure("compare_fail bundle_verify_failed")
    expected_digest, expected_name = match.group(1), match.group(2)
    if expected_name != archive.name:
        raise _CompareFailure("compare_fail bundle_verify_failed")
    if _sha256(archive) != expected_digest:
        raise _CompareFailure("compare_fail bundle_verify_failed")


def _safe_extract_archive(archive: Path, extract_root: Path) -> Path:
    archive_base = _archive_basename(archive)
    if archive_base is None:
        raise _CompareFailure("compare_fail bundle_verify_failed")
    if not archive.is_file():
        raise _CompareFailure("compare_fail bundle_verify_failed")

    _verify_archive_digest(archive)

    with tarfile.open(str(archive), mode="r:gz") as tar_handle:
        members = tar_handle.getmembers()
        for member in members:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute():
                raise _CompareFailure("compare_fail bundle_verify_failed")
            if ".." in member_path.parts:
                raise _CompareFailure("compare_fail bundle_verify_failed")
            target = (extract_root / Path(*member_path.parts)).resolve()
            if target != extract_root and extract_root not in target.parents:
                raise _CompareFailure("compare_fail bundle_verify_failed")
            if member.issym() or member.islnk() or member.ischr() or member.isblk() or member.isfifo():
                raise _CompareFailure("compare_fail bundle_verify_failed")
        tar_handle.extractall(path=extract_root, members=members)

    top_level = sorted(path for path in extract_root.iterdir())
    if len(top_level) != 1 or not top_level[0].is_dir():
        raise _CompareFailure("compare_fail bundle_verify_failed")
    if top_level[0].name != archive_base:
        raise _CompareFailure("compare_fail bundle_verify_failed")
    return top_level[0]


def _parse_manifest_steps(root: Path) -> tuple[bool, dict[str, dict[str, object]]]:
    data = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise _CompareFailure("compare_fail manifest_invalid")
    success = bool(data.get("success"))
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raise _CompareFailure("compare_fail manifest_invalid")
    out: dict[str, dict[str, object]] = {}
    for step in raw_steps:
        if not isinstance(step, dict):
            raise _CompareFailure("compare_fail manifest_invalid")
        step_id = step.get("step_id")
        if not isinstance(step_id, str) or not step_id:
            raise _CompareFailure("compare_fail manifest_invalid")
        if step_id in out:
            raise _CompareFailure("compare_fail manifest_invalid")
        status = step.get("status")
        exit_code = step.get("exit_code")
        duration_s = step.get("duration_s")
        if not isinstance(status, str) or not isinstance(exit_code, int) or not isinstance(duration_s, (int, float)):
            raise _CompareFailure("compare_fail manifest_invalid")
        out[step_id] = {
            "status": status,
            "exit_code": exit_code,
            "duration_s": round(float(duration_s), 3),
        }
    return success, out


def _parse_sha256_map(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (root / "sha256.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2:
            raise _CompareFailure("compare_fail sha256_invalid")
        digest, relpath = parts
        if relpath in out:
            raise _CompareFailure("compare_fail sha256_invalid")
        out[relpath] = digest
    return out


def _short(digest: str) -> str:
    return digest[:12]


def _format_step_duration(value: float) -> str:
    return f"{value:.3f}"


def _render_compare_html(*, compare_result: str, bundle_a_name: str, bundle_b_name: str, step_deltas: list[dict[str, object]], artifact_deltas: dict[str, object]) -> str:
    status_class = "pass" if compare_result == "PASS" else "fail"
    step_rows: list[str] = []
    for step in step_deltas:
        step_rows.append(
            "<tr>"
            f"<td>{step['step_id']}</td>"
            f"<td>{step['a_status']}</td>"
            f"<td>{step['a_exit_code']}</td>"
            f"<td>{step['a_duration_s']}</td>"
            f"<td>{step['b_status']}</td>"
            f"<td>{step['b_exit_code']}</td>"
            f"<td>{step['b_duration_s']}</td>"
            f"<td>{step['duration_delta_s']}</td>"
            "</tr>"
        )

    def list_items(values: list[str]) -> list[str]:
        if not values:
            return ["<li>None</li>"]
        return [f"<li>{value}</li>" for value in values]

    changed_rows: list[str] = []
    for entry in artifact_deltas["changed"]:
        assert isinstance(entry, dict)
        changed_rows.append(
            "<tr>"
            f"<td>{entry['relpath']}</td>"
            f"<td>{entry['a_digest_short']}</td>"
            f"<td>{entry['b_digest_short']}</td>"
            "</tr>"
        )

    changed_rows_block = [f"          {row}" for row in changed_rows] if changed_rows else ["          <tr><td colspan=\"3\">None</td></tr>"]

    html_lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>Phase 5.2 Signoff Compare Report</title>",
        "  <style>",
        "    :root { color-scheme: light dark; }",
        "    body { font-family: sans-serif; margin: 1rem auto; max-width: 80rem; padding: 0 1rem; line-height: 1.4; }",
        "    .skip-link { position: absolute; left: -9999px; top: 0; background: #fff; color: #000; padding: 0.5rem; border: 2px solid #000; }",
        "    .skip-link:focus { left: 0.5rem; z-index: 1000; }",
        "    a:focus-visible, button:focus-visible, [tabindex]:focus-visible { outline: 3px solid #005fcc; outline-offset: 2px; }",
        "    .status { font-size: 1.15rem; font-weight: 700; }",
        "    .pass { color: #0f7a2f; }",
        "    .fail { color: #a10000; }",
        "    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }",
        "    th, td { border: 1px solid #999; padding: 0.4rem; text-align: left; vertical-align: top; }",
        "    caption { text-align: left; font-weight: 700; margin-bottom: 0.4rem; }",
        "  </style>",
        "</head>",
        "<body>",
        '  <a class="skip-link" href="#content">Skip to content</a>',
        "  <header>",
        "    <h1>Phase 5.2 Signoff Compare</h1>",
        f'    <p class="status {status_class}" role="status">compare_result={compare_result}</p>',
        f"    <p>Bundle A: {bundle_a_name}</p>",
        f"    <p>Bundle B: {bundle_b_name}</p>",
        "  </header>",
        '  <main id="content">',
        "    <section aria-labelledby=\"step-delta-heading\">",
        '      <h2 id="step-delta-heading">Step delta</h2>',
        "      <table>",
        "        <caption>Deterministic step-by-step comparison from MANIFEST.json</caption>",
        "        <thead><tr><th scope=\"col\">step_id</th><th scope=\"col\">A status</th><th scope=\"col\">A exit_code</th><th scope=\"col\">A duration_s</th><th scope=\"col\">B status</th><th scope=\"col\">B exit_code</th><th scope=\"col\">B duration_s</th><th scope=\"col\">delta_s (B-A)</th></tr></thead>",
        "        <tbody>",
        *[f"          {row}" for row in step_rows],
        "        </tbody>",
        "      </table>",
        "    </section>",
        "    <section aria-labelledby=\"artifact-delta-heading\">",
        '      <h2 id="artifact-delta-heading">Artifact delta</h2>',
        "      <table>",
        "        <caption>sha256 summary</caption>",
        "        <tbody>",
        f"          <tr><th scope=\"row\">unchanged</th><td>{artifact_deltas['unchanged_count']}</td></tr>",
        f"          <tr><th scope=\"row\">changed</th><td>{artifact_deltas['changed_count']}</td></tr>",
        f"          <tr><th scope=\"row\">added</th><td>{artifact_deltas['added_count']}</td></tr>",
        f"          <tr><th scope=\"row\">removed</th><td>{artifact_deltas['removed_count']}</td></tr>",
        "        </tbody>",
        "      </table>",
        "      <h3>Changed files</h3>",
        "      <table>",
        "        <caption>Changed file digests (short)</caption>",
        "        <thead><tr><th scope=\"col\">relpath</th><th scope=\"col\">A sha256</th><th scope=\"col\">B sha256</th></tr></thead>",
        "        <tbody>",
        *changed_rows_block,
        "        </tbody>",
        "      </table>",
        "      <h3>Added files</h3>",
        "      <ul>",
        *[f"        {item}" for item in list_items(artifact_deltas["added"])],
        "      </ul>",
        "      <h3>Removed files</h3>",
        "      <ul>",
        *[f"        {item}" for item in list_items(artifact_deltas["removed"])],
        "      </ul>",
        "    </section>",
        "  </main>",
        "</body>",
        "</html>",
    ]
    return "\n".join(html_lines)


def _resolve_bundle_input(mode: str, value: str, temp_roots: list[tempfile.TemporaryDirectory[str]]) -> Path:
    path = Path(value).resolve()
    if mode == "dir":
        return path
    temp_dir = tempfile.TemporaryDirectory(prefix="phase5_2_signoff_compare_")
    temp_roots.append(temp_dir)
    extract_root = Path(temp_dir.name)
    return _safe_extract_archive(path, extract_root)


def compare_signoff_bundles(*, mode: str, bundle_a: str, bundle_b: str, out_dir: str, out: TextIO | None = None) -> int:
    out_stream = out if out is not None else os.sys.stdout
    temp_roots: list[tempfile.TemporaryDirectory[str]] = []
    try:
        root_a = _resolve_bundle_input(mode, bundle_a, temp_roots)
        root_b = _resolve_bundle_input(mode, bundle_b, temp_roots)

        rc_a = verify_signoff_bundle(str(root_a), out=None)
        rc_b = verify_signoff_bundle(str(root_b), out=None)
        if rc_a != 0 or rc_b != 0:
            out_stream.write("compare_fail bundle_verify_failed\n")
            return 1

        success_a, steps_a = _parse_manifest_steps(root_a)
        success_b, steps_b = _parse_manifest_steps(root_b)
        sha_a = _parse_sha256_map(root_a)
        sha_b = _parse_sha256_map(root_b)

        step_ids = sorted(set(steps_a.keys()) | set(steps_b.keys()))
        step_deltas: list[dict[str, object]] = []
        regression_count = 0
        for step_id in step_ids:
            data_a = steps_a.get(step_id, {"status": "MISSING", "exit_code": -1, "duration_s": 0.0})
            data_b = steps_b.get(step_id, {"status": "MISSING", "exit_code": -1, "duration_s": 0.0})
            a_status = str(data_a["status"])
            b_status = str(data_b["status"])
            if a_status == "PASS" and b_status == "FAIL":
                regression_count += 1
            a_duration = float(data_a["duration_s"])
            b_duration = float(data_b["duration_s"])
            step_deltas.append(
                {
                    "step_id": step_id,
                    "a_status": a_status,
                    "a_exit_code": int(data_a["exit_code"]),
                    "a_duration_s": _format_step_duration(a_duration),
                    "b_status": b_status,
                    "b_exit_code": int(data_b["exit_code"]),
                    "b_duration_s": _format_step_duration(b_duration),
                    "duration_delta_s": _format_step_duration(b_duration - a_duration),
                }
            )

        relpaths = sorted(set(sha_a.keys()) | set(sha_b.keys()))
        changed: list[dict[str, str]] = []
        added: list[str] = []
        removed: list[str] = []
        unchanged_count = 0
        for relpath in relpaths:
            digest_a = sha_a.get(relpath)
            digest_b = sha_b.get(relpath)
            if digest_a is None:
                added.append(relpath)
                continue
            if digest_b is None:
                removed.append(relpath)
                continue
            if digest_a == digest_b:
                unchanged_count += 1
                continue
            changed.append(
                {
                    "relpath": relpath,
                    "a_digest_short": _short(digest_a),
                    "b_digest_short": _short(digest_b),
                }
            )

        compare_result = "PASS" if regression_count == 0 and success_a and success_b else "FAIL"
        compare_exit = 0 if compare_result == "PASS" else 2

        artifact_deltas: dict[str, object] = {
            "unchanged_count": unchanged_count,
            "changed_count": len(changed),
            "added_count": len(added),
            "removed_count": len(removed),
            "changed": changed,
            "added": added,
            "removed": removed,
        }

        out_path = Path(out_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)

        summary_lines = [
            f"bundle_a={root_a.name}",
            f"bundle_b={root_b.name}",
            f"compare_result={compare_result}",
            f"regression_count={regression_count}",
            f"success_a={str(success_a).lower()}",
            f"success_b={str(success_b).lower()}",
            "step_deltas_begin",
        ]
        for step in step_deltas:
            summary_lines.append(
                "step_id={step_id} a_status={a_status} a_exit_code={a_exit_code} a_duration_s={a_duration_s} "
                "b_status={b_status} b_exit_code={b_exit_code} b_duration_s={b_duration_s} duration_delta_s={duration_delta_s}".format(
                    **step
                )
            )
        summary_lines.extend(
            [
                "step_deltas_end",
                "artifact_deltas_begin",
                f"unchanged={artifact_deltas['unchanged_count']}",
                f"changed={artifact_deltas['changed_count']}",
                f"added={artifact_deltas['added_count']}",
                f"removed={artifact_deltas['removed_count']}",
            ]
        )
        for entry in changed:
            summary_lines.append(
                f"changed relpath={entry['relpath']} digest={entry['a_digest_short']}->{entry['b_digest_short']}"
            )
        for relpath in added:
            summary_lines.append(f"added relpath={relpath}")
        for relpath in removed:
            summary_lines.append(f"removed relpath={relpath}")
        summary_lines.append("artifact_deltas_end")

        manifest = {
            "compare_version": PHASE5_2_SIGNOFF_COMPARE_V1,
            "bundle_a_name": root_a.name,
            "bundle_b_name": root_b.name,
            "regression_count": regression_count,
            "step_deltas": step_deltas,
            "artifact_deltas": artifact_deltas,
            "compare_result": compare_result,
        }

        (out_path / "COMPARE_SUMMARY.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8", newline="\n")
        with (out_path / "COMPARE_MANIFEST.json").open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(manifest, indent=2, sort_keys=True))
            handle.write("\n")
        (out_path / "compare.html").write_text(
            _render_compare_html(
                compare_result=compare_result,
                bundle_a_name=root_a.name,
                bundle_b_name=root_b.name,
                step_deltas=step_deltas,
                artifact_deltas=artifact_deltas,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

        hashes: list[tuple[str, str]] = []
        for path in sorted(out_path.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(out_path).as_posix()
            if rel == "sha256.txt":
                continue
            hashes.append((rel, _sha256(path)))
        with (out_path / "sha256.txt").open("w", encoding="utf-8", newline="\n") as handle:
            for rel, digest in hashes:
                handle.write(f"{digest}  {rel}\n")

        out_stream.write(f"compare_result={compare_result}\n")
        out_stream.write(f"regression_count={regression_count}\n")
        out_stream.write(f"artifact_changed_count={len(changed)}\n")
        return compare_exit
    except _CompareFailure as exc:
        out_stream.write(f"{exc}\n")
        return 1
    except (OSError, json.JSONDecodeError, ValueError):
        out_stream.write("compare_fail compare_format_error\n")
        return 1
    finally:
        for temp_root in temp_roots:
            temp_root.cleanup()
