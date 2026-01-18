import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cli_app import mls_poc


def _go_ready():
    go_path = shutil.which("go")
    if not go_path:
        return False, "Go toolchain not found"
    try:
        version = mls_poc.detect_go_version(go_path)
    except Exception:  # pragma: no cover - defensive skip
        return False, "Unable to determine Go version"
    if (version[0], version[1]) < mls_poc.MIN_GO_VERSION:
        return False, f"Go version too old ({version[0]}.{version[1]}.{version[2]})"
    return True, ""


@unittest.skipUnless(*_go_ready())
class MlsPocTests(unittest.TestCase):
    def test_vectors_command(self):
        proc = subprocess.run(
            [sys.executable, "-m", "cli_app.mls_poc", "vectors"],
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("ok", proc.stdout)

    def test_smoke_command(self):
        with tempfile.TemporaryDirectory() as state_dir:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli_app.mls_poc",
                    "smoke",
                    "--state-dir",
                    state_dir,
                    "--iterations",
                    "10",
                    "--save-every",
                    "5",
                ],
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)


class MlsPocDryRunTests(unittest.TestCase):
    def test_harness_uses_cached_binary(self):
        repo_root = mls_poc.find_repo_root()
        harness_cache = repo_root / "tools" / "mls_harness" / ".cache"
        harness_bin = harness_cache / "mls-harness"
        if harness_bin.exists():
            harness_bin.unlink()

        def _fake_run(cmd, **kwargs):
            if cmd[:2] == ["/usr/bin/go", "build"]:
                harness_bin.parent.mkdir(parents=True, exist_ok=True)
                harness_bin.write_text("fake", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout="build ok", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        try:
            with mock.patch("cli_app.mls_poc.ensure_go_ready", return_value="/usr/bin/go"), mock.patch(
                "cli_app.mls_poc.subprocess.run", side_effect=_fake_run
            ) as run_mock:
                returncode, stdout, stderr = mls_poc._run_harness_capture_with_status("vectors", [])
        finally:
            if harness_bin.exists():
                harness_bin.unlink()

        self.assertEqual(returncode, 0, msg=stderr)
        self.assertEqual(stdout, "ok")
        self.assertGreaterEqual(len(run_mock.call_args_list), 2)
        harness_cmd = run_mock.call_args_list[-1].args[0]
        harness_path = Path(harness_cmd[0])
        self.assertEqual(harness_path.name, "mls-harness")
        self.assertTrue(str(harness_path).endswith(str(Path("tools") / "mls_harness" / ".cache" / "mls-harness")))
        self.assertNotEqual(harness_cmd[0], "/usr/bin/go")
        self.assertNotIn("run", harness_cmd)

    def test_phase5_room_smoke_dry_run(self):
        with tempfile.TemporaryDirectory() as state_dir:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli_app.mls_poc",
                    "gw-phase5-room-smoke",
                    "--conv-id",
                    "conv_phase5_test",
                    "--state-dir",
                    state_dir,
                    "--peer-user-id",
                    "peer_user",
                    "--dry-run",
                ],
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("command"), "gw-phase5-room-smoke")
        self.assertEqual(payload.get("conv_id"), "conv_phase5_test")
        self.assertEqual(payload.get("peer_user_ids"), ["peer_user"])
        self.assertIn("steps", payload)

    def test_phase5_room_smoke_dry_run_with_add(self):
        with tempfile.TemporaryDirectory() as state_dir:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli_app.mls_poc",
                    "gw-phase5-room-smoke",
                    "--conv-id",
                    "conv_phase5_add_test",
                    "--state-dir",
                    state_dir,
                    "--peer-user-id",
                    "peer_user",
                    "--add-peer-user-id",
                    "add_peer_user",
                    "--dry-run",
                ],
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("command"), "gw-phase5-room-smoke")
        self.assertEqual(payload.get("add_peer_user_ids"), ["add_peer_user"])
        steps = payload.get("steps", [])
        step_names = {step.get("step") for step in steps}
        self.assertIn("group_add_send_envelopes", step_names)
        self.assertIn("send_second_app", step_names)
        add_steps = [step for step in steps if step.get("step") == "group_add_send_envelopes"]
        self.assertEqual(len(add_steps), 1)
        add_envelopes = add_steps[0].get("envelopes", [])
        self.assertGreaterEqual(len(add_envelopes), 3)
        self.assertEqual(add_envelopes[0].get("name"), "add_proposal")
        self.assertEqual(add_envelopes[1].get("name"), "add_welcome")
        self.assertEqual(add_envelopes[2].get("name"), "add_commit")

    def test_uninitialized_commit_error_helper(self):
        self.assertTrue(mls_poc._is_uninitialized_commit_error("participant state not initialized"))
        self.assertFalse(mls_poc._is_uninitialized_commit_error("unexpected epoch mismatch"))


if __name__ == "__main__":
    unittest.main()
