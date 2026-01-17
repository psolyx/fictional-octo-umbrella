import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
