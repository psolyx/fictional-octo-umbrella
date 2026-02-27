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
            'char in {"b"}',
            'char in {"u"}',
            'char in {"x"}',
            'char in {"X"}',
            'char in {"+"}',
            'char in {"-"}',
            'char in {"m", "M"}',
            'char in {"n", "N"}',
            'char in {"p", "P"}',
            'char in {"z"}',
            'char in {"A"}',
            'char in {"H"}',
            'char in {"t"}',
            'return "conv_mark_read"',
            'return "conv_mark_all_read"',
            'return "conv_recover_pruned"',
            'return f"{self.room_modal_action}_submit"',
            'self._open_room_modal("room_create")',
            'self._open_room_modal("room_invite")',
            'self._open_room_modal("room_remove")',
            'self._open_room_modal("room_ban")',
            'self._open_room_modal("room_unban")',
            'self._open_room_modal("room_mute")',
            'self._open_room_modal("room_unmute")',
            'self._open_room_modal("room_promote")',
            'self._open_room_modal("room_demote")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_model)

    def test_gateway_client_rooms_wrappers_and_usage(self):
        for marker in (
            'def rooms_create(',
            'def dms_create(',
            'def rooms_invite(',
            'def rooms_remove(',
            'def rooms_promote(',
            'def rooms_demote(',
            'def rooms_ban(',
            'def rooms_unban(',
            'def rooms_bans(',
            'def rooms_mute(',
            'def rooms_unmute(',
            'def rooms_mutes(',
            'def rooms_members(',
            'def conversations_mark_read(',
            'def conversations_mark_all_read(',
            'def conversations_set_title(',
            'def conversations_set_label(',
            'def conversations_set_pinned(',
            'def conversations_set_muted(',
            'def conversations_set_archived(',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.gateway_client)
        for marker in (
            'gateway_client.rooms_create',
            'gateway_client.rooms_invite',
            'gateway_client.rooms_remove',
            'gateway_client.rooms_promote',
            'gateway_client.rooms_demote',
            'gateway_client.rooms_ban',
            'gateway_client.rooms_unban',
            'gateway_client.rooms_mute',
            'gateway_client.rooms_unmute',
            'gateway_client.rooms_bans',
            'gateway_client.rooms_mutes',
            'gateway_client.rooms_members',
            'room_roster_toggle_view',
            'gateway_client.conversations_mark_read',
            'gateway_client.conversations_mark_all_read',
            'gateway_client.conversations_set_title',
            'gateway_client.conversations_set_label',
            'gateway_client.conversations_set_pinned',
            'gateway_client.conversations_set_muted',
            'gateway_client.conversations_set_archived',
            'Room roster',
            'Room bans',
            'Room mutes',
            'Add selected to modal members',
            'mark_read',
            'mark_all_read',
            'conv_mark_all_read',
            'conv_toggle_pinned',
            'conv_toggle_muted',
            'conv_toggle_archived',
            'conv_toggle_show_archived',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app)
        self.assertIn('/v1/dms/create', self.gateway_client)

    def test_tui_message_lifecycle_and_preview_contracts(self):
        for marker in (
            'retry_failed_send',
            '[pending msg_id=',
            '[delivered',
            'last_preview',
            'R: retry failed',
            'rate_limited:',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.tui_app if marker in self.tui_app else self.tui_model)

    def test_tui_help_overlay_contracts(self):
        self.assertIn('if key == "?"', self.tui_model)
        self.assertIn('"Keybindings"', self.tui_app)
        self.assertIn('"Press Esc to close (or q)"', self.tui_app)
        self.assertIn('r mark read', self.tui_app)
        self.assertIn('Ctrl-R mark all read', self.tui_app)
        self.assertIn('z mute/unmute', self.tui_app)
        self.assertIn('x mute member', self.tui_app)
        self.assertIn('X unmute member', self.tui_app)
        self.assertIn('A archive/unarchive', self.tui_app)
        self.assertIn('H show/hide archived', self.tui_app)

    def test_tui_pruned_history_markers(self):
        self.assertIn('HISTORY PRUNED', self.tui_app)
        self.assertIn('Press g to recover', self.tui_app)
        self.assertIn('g recover pruned history', self.tui_app)

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
