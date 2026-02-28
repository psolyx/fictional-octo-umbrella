import pathlib
import unittest


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
