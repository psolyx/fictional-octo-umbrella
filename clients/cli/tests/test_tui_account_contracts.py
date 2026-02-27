import pathlib
import unittest

from cli_app import phase5_2_smoke_lite


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
            "logout_server",
            "logout_all_devices",
            "sessions_list",
            "revoke_session",
            "revoke_device",
            "identity_import",
            "identity_export",
            "identity_new",
            "account_reauth",
            "rotate_device",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_model)

    def test_tui_app_handles_account_actions(self):
        for marker in (
            'elif action == "gw_start"',
            'elif action == "gw_resume"',
            'elif action == "logout"',
            'elif action == "logout_server"',
            'elif action == "logout_all_devices"',
            'elif action == "sessions_list"',
            'elif action == "revoke_session"',
            'elif action == "revoke_device"',
            'elif action == "identity_import"',
            'elif action == "identity_export"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app)

    def test_tui_redaction_hooks_present(self):
        self.assertIn("from cli_app.redact import redact_text", self.tui_app)
        self.assertIn("model.social_status_line = redact_text(text)", self.tui_app)
        self.assertIn("redact_text(text)", self.tui_model)


    def test_session_expired_contract_markers(self):
        self.assertIn('session expired', self.tui_app)
        self.assertIn('auth_state', self.tui_model)
        self.assertIn('"expired"', self.tui_model)
        self.assertIn('elif action == "account_reauth"', self.tui_app)

    def test_phase5_2_smoke_lite_contract_markers(self):
        self.assertTrue(hasattr(phase5_2_smoke_lite, "run_smoke_lite_http"))
        self.assertIn("PHASE5_2_SMOKE_LITE_BEGIN", phase5_2_smoke_lite.PHASE5_2_SMOKE_LITE_BEGIN)
        self.assertIn("PHASE5_2_SMOKE_LITE_OK", phase5_2_smoke_lite.PHASE5_2_SMOKE_LITE_OK)
        self.assertIn("PHASE5_2_SMOKE_LITE_END", phase5_2_smoke_lite.PHASE5_2_SMOKE_LITE_END)

if __name__ == "__main__":
    unittest.main()
