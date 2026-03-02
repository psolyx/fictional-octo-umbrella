from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path
from typing import TextIO

from cli_app.phase5_2_signoff_verify import verify_signoff_bundle
from cli_app.signoff_bundle_io import safe_extract_tgz, sha256_file, verify_sha256_manifest
from cli_app.signoff_html import render_signoff_compare

PHASE5_2_SIGNOFF_COMPARE_BEGIN = "PHASE5_2_SIGNOFF_COMPARE_BEGIN"
PHASE5_2_SIGNOFF_COMPARE_OK = "PHASE5_2_SIGNOFF_COMPARE_OK"
PHASE5_2_SIGNOFF_COMPARE_END = "PHASE5_2_SIGNOFF_COMPARE_END"
PHASE5_2_SIGNOFF_COMPARE_V1 = "PHASE5_2_SIGNOFF_COMPARE_V1"


class _CompareFailure(Exception):
    pass


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
    verify_sha256_manifest(root)
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


def _resolve_bundle_input(mode: str, value: str, temp_roots: list[tempfile.TemporaryDirectory[str]]) -> Path:
    path = Path(value).resolve()
    if mode == "dir":
        return path
    temp_dir = tempfile.TemporaryDirectory(prefix="phase5_2_signoff_compare_")
    temp_roots.append(temp_dir)
    extract_root = Path(temp_dir.name)
    try:
        return safe_extract_tgz(path, temp_root=extract_root)
    except ValueError as exc:
        raise _CompareFailure("compare_fail bundle_verify_failed") from exc


def compare_signoff_bundles(*, mode: str, bundle_a: str, bundle_b: str, out_dir: str, out: TextIO | None = None) -> int:
    out_stream = out if out is not None else os.sys.stdout
    temp_roots: list[tempfile.TemporaryDirectory[str]] = []
    try:
        root_a = _resolve_bundle_input(mode, bundle_a, temp_roots)
        root_b = _resolve_bundle_input(mode, bundle_b, temp_roots)

        verify_log = io.StringIO()
        rc_a = verify_signoff_bundle(str(root_a), out=verify_log)
        rc_b = verify_signoff_bundle(str(root_b), out=verify_log)
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
        step_rows = [
            [
                str(step["step_id"]),
                str(step["a_status"]),
                str(step["a_exit_code"]),
                str(step["a_duration_s"]),
                str(step["b_status"]),
                str(step["b_exit_code"]),
                str(step["b_duration_s"]),
                str(step["duration_delta_s"]),
            ]
            for step in step_deltas
        ]
        artifact_sections = {
            "changed": [
                [
                    str(entry["relpath"]),
                    str(entry["a_digest_short"]),
                    str(entry["b_digest_short"]),
                ]
                for entry in changed
            ],
            "added": [[str(value), "", ""] for value in added],
            "removed": [[str(value), "", ""] for value in removed],
        }
        (out_path / "compare.html").write_text(
            render_signoff_compare(
                compare_manifest=manifest,
                step_rows=step_rows,
                artifact_sections=artifact_sections,
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
            hashes.append((rel, sha256_file(path)))
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
