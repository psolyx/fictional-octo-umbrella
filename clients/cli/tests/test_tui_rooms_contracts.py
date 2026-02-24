import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestTuiRoomsContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tui_model = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "tui_model.py").read_text(encoding="utf-8")
        cls.tui_app = (REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "tui_app.py").read_text(encoding="utf-8")
        cls.gateway_client = (
            REPO_ROOT / "clients" / "cli" / "src" / "cli_app" / "gateway_client.py"
        ).read_text(encoding="utf-8")

    def test_tui_model_has_room_keybindings(self):
        for marker in (
            'if key == "CTRL_R"',
            'char in {"I"}',
            'char in {"K"}',
            'char in {"+"}',
            'char in {"-"}',
            'char in {"m", "M"}',
            'return f"{self.room_modal_action}_submit"',
            'self._open_room_modal("room_create")',
            'self._open_room_modal("room_invite")',
            'self._open_room_modal("room_remove")',
            'self._open_room_modal("room_promote")',
            'self._open_room_modal("room_demote")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_model)

    def test_gateway_client_rooms_wrappers_and_usage(self):
        for marker in (
            'def rooms_create(',
            'def rooms_invite(',
            'def rooms_remove(',
            'def rooms_promote(',
            'def rooms_demote(',
            'def rooms_members(',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.gateway_client)
        for marker in (
            'gateway_client.rooms_create',
            'gateway_client.rooms_invite',
            'gateway_client.rooms_remove',
            'gateway_client.rooms_promote',
            'gateway_client.rooms_demote',
            'gateway_client.rooms_members',
            'Room roster',
            'Add selected to modal members',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app)

    def test_tui_message_lifecycle_and_preview_contracts(self):
        for marker in (
            'retry_failed_send',
            '[pending msg_id=',
            '[delivered',
            'last_preview',
            'R: retry failed',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app if marker in self.tui_app else self.tui_model)

    def test_tui_help_overlay_contracts(self):
        self.assertIn('if key == "?"', self.tui_model)
        self.assertIn('"Keybindings"', self.tui_app)
        self.assertIn('"Press Esc to close (or q)"', self.tui_app)

    def test_tui_presence_room_markers(self):
        for marker in (
            '/v1/presence/watch',
            '/v1/presence/status',
            'presence.update',
            'online',
            'offline',
            'unavailable',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app)


if __name__ == "__main__":
    unittest.main()
