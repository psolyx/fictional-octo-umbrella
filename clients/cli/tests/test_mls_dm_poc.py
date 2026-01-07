import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from cli_app import identity_store, mls_poc
from cli_app.tui_app import _parse_dm_init_output, _run_action
from cli_app.tui_model import TuiModel


class MlsPocDmHandlerTests(unittest.TestCase):
    def test_dm_keypackage_calls_harness(self):
        args = SimpleNamespace(state_dir="state", name="alice", seed=7)
        with mock.patch("cli_app.mls_poc.run_harness") as run_harness:
            mls_poc.handle_dm_keypackage(args)
            run_harness.assert_called_once_with(
                "dm-keypackage",
                ["--state-dir", "state", "--name", "alice", "--seed", "7"],
            )

    def test_dm_init_calls_harness(self):
        args = SimpleNamespace(
            state_dir="state",
            peer_keypackage="peer",
            group_id="group",
            seed=1337,
        )
        with mock.patch("cli_app.mls_poc.run_harness") as run_harness:
            mls_poc.handle_dm_init(args)
            run_harness.assert_called_once_with(
                "dm-init",
                [
                    "--state-dir",
                    "state",
                    "--peer-keypackage",
                    "peer",
                    "--group-id",
                    "group",
                    "--seed",
                    "1337",
                ],
            )

    def test_dm_join_calls_harness(self):
        args = SimpleNamespace(state_dir="state", welcome="welcome")
        with mock.patch("cli_app.mls_poc.run_harness") as run_harness:
            mls_poc.handle_dm_join(args)
            run_harness.assert_called_once_with(
                "dm-join",
                ["--state-dir", "state", "--welcome", "welcome"],
            )

    def test_dm_commit_apply_calls_harness(self):
        args = SimpleNamespace(state_dir="state", commit="commit")
        with mock.patch("cli_app.mls_poc.run_harness") as run_harness:
            mls_poc.handle_dm_commit_apply(args)
            run_harness.assert_called_once_with(
                "dm-commit-apply",
                ["--state-dir", "state", "--commit", "commit"],
            )

    def test_dm_encrypt_calls_harness(self):
        args = SimpleNamespace(state_dir="state", plaintext="hello")
        with mock.patch("cli_app.mls_poc.run_harness") as run_harness:
            mls_poc.handle_dm_encrypt(args)
            run_harness.assert_called_once_with(
                "dm-encrypt",
                ["--state-dir", "state", "--plaintext", "hello"],
            )

    def test_dm_decrypt_calls_harness(self):
        args = SimpleNamespace(state_dir="state", ciphertext="ciphertext")
        with mock.patch("cli_app.mls_poc.run_harness") as run_harness:
            mls_poc.handle_dm_decrypt(args)
            run_harness.assert_called_once_with(
                "dm-decrypt",
                ["--state-dir", "state", "--ciphertext", "ciphertext"],
            )


class MlsPocDmTuiTests(unittest.TestCase):
    def test_parse_dm_init_output(self):
        lines = ["noise", '{"welcome": "w", "commit": "c"}']
        parsed = _parse_dm_init_output(lines)
        self.assertEqual(parsed, ("w", "c"))

    def test_dm_init_updates_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = f"{tmpdir}/settings.json"
            identity_path = f"{tmpdir}/identity.json"
            identity = identity_store.load_or_create_identity(identity_path)
            model = TuiModel(
                {},
                settings_path=settings_path,
                identity=identity,
                identity_path=identity_path,
            )

            model.set_field_value("dm_state_dir", "/tmp/state")
            model.set_field_value("dm_peer_keypackage", "peer-keypackage")
            model.set_field_value("dm_group_id", "group-id")
            model.set_field_value("dm_seed", "1337")
            model.selected_menu = model.menu_items.index("dm_init")

            def fake_run_harness(_subcommand, _extra_args):
                print('{"welcome":"welcome-b64","commit":"commit-b64"}')
                return 0

            log_lines = []
            with mock.patch("cli_app.mls_poc.run_harness", side_effect=fake_run_harness):
                _run_action(model, log_lines.extend)

            fields = model.render().fields
            self.assertEqual(fields["dm_welcome"], "welcome-b64")
            self.assertEqual(fields["dm_commit"], "commit-b64")


if __name__ == "__main__":
    unittest.main()
