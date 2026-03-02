import hashlib
import io
import os
import pathlib
import re
import subprocess
import tarfile
import tempfile
import unittest

from cli_app.signoff_bundle_io import build_deterministic_tgz, safe_extract_tgz, verify_sha256_manifest
from cli_app.signoff_html import render_signoff_catalog, render_signoff_compare, render_signoff_index


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"
PRODUCTION_SPEC_PATH = REPO_ROOT / "clients" / "docs" / "production_clients_exit_criteria.md"
ASPECTS_PHASE6_PATH = REPO_ROOT / "clients" / "docs" / "aspects_phase6.md"
SECURITY_CHECKLIST_PATH = REPO_ROOT / "clients" / "docs" / "baseline_security_checklist.md"
A11Y_CHECKLIST_PATH = REPO_ROOT / "clients" / "docs" / "baseline_accessibility_checklist.md"


class TestRoadmapSpecContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roadmap = ROADMAP_PATH.read_text(encoding="utf-8")
        cls.production_spec = PRODUCTION_SPEC_PATH.read_text(encoding="utf-8")
        cls.aspects_phase6 = ASPECTS_PHASE6_PATH.read_text(encoding="utf-8") if ASPECTS_PHASE6_PATH.exists() else ""

    def test_phase_5_2_section_exists_with_required_capabilities(self):
        self.assertIn("### Phase 5.2 — Production clients (Web UI + TUI)", self.roadmap)
        for marker in (
            "Account lifecycle",
            "Profile",
            "DMs",
            "Rooms",
            "Timeline",
            "MySpace-like",
            "Friends list",
            "Home feed",
            "follow/unfollow",
            "identity import/export",
            "Pruning recovery UX",
            "OWASP ASVS",
            "WCAG 2.x",
            "Risk retired",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.roadmap)

    def test_phase_5a_harness_and_phase_5_2_production_gate_contract(self):
        self.assertIn("#### Phase 5a — Web protocol/interop harness", self.roadmap)
        self.assertIn("Phase 5a remains a harness milestone", self.roadmap)
        self.assertIn("production readiness is gated only when Phase 5.2 criteria are satisfied", self.roadmap)

    def test_phase_6_is_aspects_and_phase_7_is_federation(self):
        self.assertIn("### Phase 6 — Aspects (E2EE audience groups) planning gate", self.roadmap)
        self.assertIn("planning only", self.roadmap)
        self.assertIn("### Phase 7 — Gateway federation v2 (relay-to-home)", self.roadmap)

    def test_aspects_phase6_doc_exists_and_has_required_markers(self):
        self.assertTrue(ASPECTS_PHASE6_PATH.exists(), msg="aspects phase 6 planning doc must exist")
        for marker in (
            "planning-only",
            "Encrypted payload envelope contract",
            "aspect_id",
            "key_id",
            "alg",
            "nonce_b64",
            "aad_b64",
            "ciphertext_b64",
            "Key distribution posture (MLS-backed)",
            "Rotation rules",
            "Non-member UX",
            "RFC 9420",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.aspects_phase6)

    def test_production_clients_spec_exists_and_has_required_sections(self):
        self.assertTrue(PRODUCTION_SPEC_PATH.exists(), msg="production clients spec doc must exist")
        for marker in (
            "# Production clients exit criteria (Phase 5.2)",
            "Definition of Done — Web UI",
            "Definition of Done — TUI",
            "Account lifecycle",
            "Profile",
            "DMs",
            "Rooms",
            "Timeline",
            "MySpace-like profile acceptance contract",
            "Friends + Home feed",
            "follow/unfollow",
            "identity import/export",
            "Pruning recovery UX requirements",
            "Security checklist",
            "Accessibility checklist",
            "Non-goals / out of scope",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.production_spec)

    def test_phase5_2_smoke_lite_doc_markers_exist(self):
        self.assertIn("PHASE5_2_SMOKE_LITE", self.production_spec)
        self.assertIn("python -m cli_app.phase5_2_smoke_lite_main", self.production_spec)

    def test_phase5_2_signoff_bundle_doc_markers_exist(self):
        self.assertIn("PHASE5_2_SIGNOFF_BUNDLE", self.production_spec)
        self.assertIn("PHASE5_2_SIGNOFF_ARCHIVE", self.production_spec)
        self.assertIn("./scripts/phase5_2_signoff_bundle.sh", self.production_spec)
        self.assertIn("index.html", self.production_spec)
        self.assertIn("PHASE5_2_SIGNOFF_HTML_RENDERER", self.production_spec)

    def test_phase5_2_signoff_verify_doc_markers_exist(self):
        self.assertIn("PHASE5_2_SIGNOFF_VERIFY", self.production_spec)
        self.assertIn("./scripts/phase5_2_signoff_verify.sh", self.production_spec)

    def test_phase5_2_signoff_compare_doc_markers_exist(self):
        self.assertIn("PHASE5_2_SIGNOFF_COMPARE", self.production_spec)
        self.assertIn("./scripts/phase5_2_signoff_compare.sh", self.production_spec)

    def test_phase5_2_signoff_catalog_doc_markers_exist(self):
        self.assertIn("PHASE5_2_SIGNOFF_CATALOG", self.production_spec)
        self.assertIn("./scripts/phase5_2_signoff_catalog.sh", self.production_spec)

    def test_phase5_2_signoff_autopilot_doc_markers_exist(self):
        self.assertIn("PHASE5_2_SIGNOFF_AUTOPILOT", self.production_spec)
        self.assertIn("./scripts/phase5_2_signoff_autopilot.sh", self.production_spec)


    def test_phase5_2_signoff_compare_dry_run_markers_are_stable(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "clients/cli/src"
        env["COMPARE_DRY_RUN"] = "1"
        env["A_EVID_DIR"] = "evidence/a"
        env["B_EVID_DIR"] = "evidence/b"
        env.pop("A_ARCHIVE_PATH", None)
        env.pop("B_ARCHIVE_PATH", None)
        proc = subprocess.run(
            ["python", "-m", "cli_app.phase5_2_signoff_compare_main"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        self.assertIn("PHASE5_2_SIGNOFF_COMPARE_BEGIN", lines)
        self.assertIn("PHASE5_2_SIGNOFF_COMPARE_V1", lines)
        self.assertIn("mode=dir", lines)
        self.assertIn("PHASE5_2_SIGNOFF_COMPARE_END", lines)
        timestamp_pattern = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}T\d{6}Z")
        for line in lines:
            with self.subTest(line=line):
                self.assertIsNone(timestamp_pattern.search(line))


    def test_phase5_2_signoff_catalog_dry_run_markers_are_stable(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "clients/cli/src"
        env["CATALOG_DRY_RUN"] = "1"
        env["EVIDENCE_ROOT"] = "evidence"
        proc = subprocess.run(
            ["python", "-m", "cli_app.phase5_2_signoff_catalog_main"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        self.assertIn("PHASE5_2_SIGNOFF_CATALOG_BEGIN", lines)
        self.assertIn("PHASE5_2_SIGNOFF_CATALOG_V1", lines)
        self.assertIn("PHASE5_2_SIGNOFF_CATALOG_END", lines)
        self.assertIn("evidence_root_basename=evidence", lines)
        timestamp_pattern = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}T\d{6}Z")
        for line in lines:
            with self.subTest(line=line):
                self.assertIsNone(timestamp_pattern.search(line))

    def test_phase5_2_signoff_autopilot_dry_run_markers_are_stable(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "clients/cli/src"
        env["AUTOPILOT_DRY_RUN"] = "1"
        env["EVIDENCE_ROOT"] = "evidence"
        proc = subprocess.run(
            ["python", "-m", "cli_app.phase5_2_signoff_autopilot_main"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        self.assertIn("PHASE5_2_SIGNOFF_AUTOPILOT_BEGIN", lines)
        self.assertIn("PHASE5_2_SIGNOFF_AUTOPILOT_V1", lines)
        self.assertIn("evidence_root_basename=evidence", lines)
        self.assertIn("PHASE5_2_SIGNOFF_AUTOPILOT_END", lines)
        timestamp_pattern = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}T\d{6}Z")
        for line in lines:
            with self.subTest(line=line):
                self.assertIsNone(timestamp_pattern.search(line))

    def test_phase5_2_signoff_io_hardening_marker_exists(self):
        self.assertIn("PHASE5_2_SIGNOFF_IO_HARDENING", self.production_spec)

    def test_safe_extract_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            archive = tmp_path / "bundle.tgz"
            with tarfile.open(archive, "w:gz") as tf:
                payload = b"x"
                info = tarfile.TarInfo("bundle/../evil.txt")
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (tmp_path / "bundle.tgz.sha256").write_text(f"{digest}  bundle.tgz\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "archive_member_parent_ref"):
                safe_extract_tgz(archive, temp_root=tmp_path / "extract")

    def test_safe_extract_rejects_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            archive = tmp_path / "bundle.tgz"
            with tarfile.open(archive, "w:gz") as tf:
                payload = b"x"
                info = tarfile.TarInfo("/abs.txt")
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (tmp_path / "bundle.tgz.sha256").write_text(f"{digest}  bundle.tgz\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "archive_member_absolute"):
                safe_extract_tgz(archive, temp_root=tmp_path / "extract")

    def test_safe_extract_rejects_symlink_or_hardlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            archive = tmp_path / "bundle.tgz"
            with tarfile.open(archive, "w:gz") as tf:
                info = tarfile.TarInfo("bundle/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "target"
                tf.addfile(info)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (tmp_path / "bundle.tgz.sha256").write_text(f"{digest}  bundle.tgz\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "archive_member_type_unsupported"):
                safe_extract_tgz(archive, temp_root=tmp_path / "extract")

    def test_build_deterministic_tgz_is_byte_stable_for_same_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            bundle = tmp_path / "bundle"
            (bundle / "dir").mkdir(parents=True)
            (bundle / "a.txt").write_text("alpha\n", encoding="utf-8")
            (bundle / "dir" / "b.txt").write_text("beta\n", encoding="utf-8")

            out1 = tmp_path / "out1"
            out2 = tmp_path / "out2"
            out1.mkdir()
            out2.mkdir()
            archive1, sha1 = build_deterministic_tgz(bundle, out_dir=out1)
            archive2, sha2 = build_deterministic_tgz(bundle, out_dir=out2)

            self.assertEqual(hashlib.sha256(archive1.read_bytes()).hexdigest(), hashlib.sha256(archive2.read_bytes()).hexdigest())
            self.assertRegex(sha1.read_text(encoding="utf-8").strip(), r"^[0-9a-f]{64}  bundle\.tgz$")
            self.assertRegex(sha2.read_text(encoding="utf-8").strip(), r"^[0-9a-f]{64}  bundle\.tgz$")

    def test_verify_sha256_manifest_rejects_unsorted_or_mismatched_file_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            (tmp_path / "a.txt").write_text("a", encoding="utf-8")
            (tmp_path / "b.txt").write_text("b", encoding="utf-8")
            da = hashlib.sha256((tmp_path / "a.txt").read_bytes()).hexdigest()
            db = hashlib.sha256((tmp_path / "b.txt").read_bytes()).hexdigest()
            (tmp_path / "sha256.txt").write_text(f"{db}  b.txt\n{da}  a.txt\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sha256_not_sorted"):
                verify_sha256_manifest(tmp_path)

            (tmp_path / "sha256.txt").write_text(f"{da}  a.txt\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sha256_file_set_mismatch"):
                verify_sha256_manifest(tmp_path)

    def test_signoff_index_html_has_required_a11y_structure(self):
        manifest = {
            "success": True,
            "steps": [
                {
                    "step_id": "t01",
                    "label": "gateway_test",
                    "status": "PASS",
                    "duration_s": 1.234,
                    "exit_code": 0,
                }
            ],
        }
        rendered = render_signoff_index(
            manifest=manifest,
            artifacts=[("SIGNOFF_SUMMARY.txt", "SIGNOFF_SUMMARY.txt")],
            result="PASS",
            notes=["./scripts/phase5_2_signoff_verify.sh EVID_DIR=./evidence/<bundle-path>"],
        )
        self.assertIn("<!doctype html>", rendered)
        self.assertIn('<html lang="en">', rendered)
        self.assertIn("Skip to content", rendered)
        self.assertIn("<caption>", rendered)
        self.assertIn('<th scope="col">', rendered)
        self.assertIn(":focus-visible", rendered)

    def test_signoff_catalog_html_has_required_a11y_structure(self):
        rendered = render_signoff_catalog(
            {
                "evidence_root_basename": "evidence",
                "bundle_count": 1,
                "compare_count": 1,
                "bundles": [
                    {
                        "created_utc": "2026-01-01T00:00:00Z",
                        "result": "PASS",
                        "total_duration_s": 1.0,
                        "index_href": "../bundle/index.html",
                        "sha256_href": "../bundle/sha256.txt",
                        "manifest_href": "../bundle/MANIFEST.json",
                    }
                ],
                "compares": [
                    {
                        "created_utc": "2026-01-01T00:00:00Z",
                        "result": "FAIL",
                        "regression_count": 1,
                        "compare_href": "../compare/compare.html",
                        "manifest_href": "../compare/COMPARE_MANIFEST.json",
                    }
                ],
            }
        )
        self.assertIn("<!doctype html>", rendered)
        self.assertIn('<html lang="en">', rendered)
        self.assertIn("Skip to content", rendered)
        self.assertIn("<caption>", rendered)
        self.assertIn(':focus-visible', rendered)

    def test_signoff_compare_html_has_required_a11y_structure(self):
        compare_manifest = {"compare_result": "FAIL", "regression_count": 2}
        rendered = render_signoff_compare(
            compare_manifest=compare_manifest,
            step_rows=[["t01", "PASS", "0", "1.000", "FAIL", "1", "2.000", "1.000"]],
            artifact_sections={
                "changed": [["a.txt", "aaa", "bbb"]],
                "added": [["b.txt", "", ""]],
                "removed": [["c.txt", "", ""]],
            },
        )
        self.assertIn("<!doctype html>", rendered)
        self.assertIn('<html lang="en">', rendered)
        self.assertIn("Skip to content", rendered)
        self.assertIn("<caption>", rendered)
        self.assertIn('<th scope="col">', rendered)
        self.assertIn(":focus-visible", rendered)

    def test_renderer_escapes_untrusted_strings(self):
        manifest = {
            "success": False,
            "steps": [
                {
                    "step_id": "<script>alert(1)</script>",
                    "label": 'A & B "quoted"',
                    "status": "FAIL",
                    "duration_s": 0,
                    "exit_code": 1,
                }
            ],
        }
        rendered = render_signoff_index(
            manifest=manifest,
            artifacts=[('<script>.txt', 'artifact "x" & y')],
            result="FAIL",
            notes=['cmd "quoted" & <tag>'],
        )
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("A &amp; B &quot;quoted&quot;", rendered)
        self.assertIn("artifact &quot;x&quot; &amp; y", rendered)
        self.assertNotIn("<script>alert(1)</script>", rendered)

    def test_renderer_output_is_deterministic_for_same_inputs(self):
        manifest = {
            "success": True,
            "steps": [
                {
                    "step_id": "t01",
                    "label": "stable",
                    "status": "PASS",
                    "duration_s": 3.210,
                    "exit_code": 0,
                }
            ],
        }
        artifacts = [("sha256.txt", "sha256.txt")]
        notes = ["./scripts/phase5_2_signoff_compare.sh A_EVID_DIR=./evidence/<bundle-a> B_EVID_DIR=./evidence/<bundle-b>"]
        first = render_signoff_index(manifest=manifest, artifacts=artifacts, result="PASS", notes=notes)
        second = render_signoff_index(manifest=manifest, artifacts=artifacts, result="PASS", notes=notes)
        self.assertEqual(first, second)

    def test_phase5_2_static_audit_checklist_markers_exist(self):
        self.assertTrue(SECURITY_CHECKLIST_PATH.exists(), msg="baseline security checklist must exist")
        self.assertTrue(A11Y_CHECKLIST_PATH.exists(), msg="baseline accessibility checklist must exist")
        security_text = SECURITY_CHECKLIST_PATH.read_text(encoding="utf-8")
        a11y_text = A11Y_CHECKLIST_PATH.read_text(encoding="utf-8")
        self.assertIn("SECURITY_CHECKLIST_V1", security_text)
        self.assertIn("A11Y_CHECKLIST_V1", a11y_text)
        self.assertIn("PHASE5_2_STATIC_AUDIT", self.production_spec)

if __name__ == "__main__":
    unittest.main()
