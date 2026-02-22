import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"
PRODUCTION_SPEC_PATH = REPO_ROOT / "clients" / "docs" / "production_clients_exit_criteria.md"


class TestRoadmapSpecContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roadmap = ROADMAP_PATH.read_text(encoding="utf-8")
        cls.production_spec = PRODUCTION_SPEC_PATH.read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
