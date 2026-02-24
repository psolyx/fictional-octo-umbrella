import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestTuiAccountContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tui_app = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "tui_app.py").read_text(encoding="utf-8")
        cls.tui_model = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "tui_model.py").read_text(encoding="utf-8")

    def test_tui_menu_has_account_actions(self):
        for marker in (
            "gw_start",
            "gw_resume",
            "logout",
            "identity_import",
            "identity_export",
            "identity_new",
            "rotate_device",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_model)

    def test_tui_app_handles_account_actions(self):
        for marker in (
            'elif action == "gw_start"',
            'elif action == "gw_resume"',
            'elif action == "logout"',
            'elif action == "identity_import"',
            'elif action == "identity_export"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app)

    def test_tui_redaction_hooks_present(self):
        self.assertIn("from cli_app.redact import redact_text", self.tui_app)
        self.assertIn("model.social_status_line = redact_text(text)", self.tui_app)
        self.assertIn("redact_text(text)", self.tui_model)


if __name__ == "__main__":
    unittest.main()
