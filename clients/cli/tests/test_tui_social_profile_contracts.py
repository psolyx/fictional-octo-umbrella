import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestTuiSocialProfileContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tui_app = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "tui_app.py").read_text(encoding="utf-8")
        cls.tui_model = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "tui_model.py").read_text(encoding="utf-8")
        cls.gateway_client = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "gateway_client.py").read_text(encoding="utf-8")
        cls.social_helpers = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "social.py").read_text(encoding="utf-8")
        cls.tui_main = (REPO_ROOT / "clients" / "tui" / "src" / "tui_app" / "__main__.py").read_text(encoding="utf-8")

    def test_profile_marker_and_social_endpoints_contract(self):
        self.assertIn("MySpace-style profile", self.tui_app)
        if "/v1/social/profile" not in self.tui_app or "/v1/social/feed" not in self.tui_app:
            self.assertIn("def fetch_social_profile", self.social_helpers)
            self.assertIn("def fetch_social_feed", self.social_helpers)
            self.assertIn("/v1/social/profile", self.social_helpers)
            self.assertIn("/v1/social/feed", self.social_helpers)

    def test_social_view_mode_and_key_contracts(self):
        self.assertIn("social_view_mode", self.tui_model)
        self.assertIn('char in {"v", "V"}', self.tui_model)
        self.assertIn('char in {"f", "F"}', self.tui_model)
        self.assertIn('char in {"d", "D"}', self.tui_model)
        self.assertIn('char in {"B"}', self.tui_model)
        self.assertIn('if self.focus_area == "social" and self.social_active', self.tui_model)

    def test_social_start_dm_contracts(self):
        self.assertIn('/v1/dms/create', self.gateway_client)
        self.assertIn('def dms_create(', self.gateway_client)
        self.assertIn('def presence_blocklist(', self.gateway_client)
        self.assertIn('Start DM (D)', self.tui_app)

    def test_abuse_control_markers(self):
        for marker in (
            'BLOCKED',
            'social_toggle_block',
            'rate_limited:',
            '/v1/presence/blocklist',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app if marker != '/v1/presence/blocklist' else self.gateway_client)


    def test_conversation_refresh_contract(self):
        self.assertIn('return "conv_refresh"', self.tui_model)
        self.assertIn('gateway_client.conversations_list', self.tui_app)
        self.assertIn('return "conv_next_unread"', self.tui_model)
        self.assertIn('U: next unread', self.tui_app)
        self.assertIn('[unread', self.tui_app)

    def test_clients_tui_wrapper_dispatches_to_cli_app(self):
        self.assertIn("from cli_app.tui_app import main as cli_tui_main", self.tui_main)
        self.assertIn("return cli_tui_main()", self.tui_main)

    def test_social_publish_queue_markers(self):
        for marker in (
            'social_publish_retry_failed',
            'Pending publishes',
            'pending',
            'confirmed',
            'failed',
            'char in {"R"}',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_model if marker in self.tui_model else self.tui_app)


if __name__ == "__main__":
    unittest.main()
