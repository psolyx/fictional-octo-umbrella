import shutil
import subprocess
import tempfile
import unittest
from typing import Dict

import os
from pathlib import Path


class TestMLSHarnessSmoke(unittest.TestCase):
    def test_smoke_runs(self) -> None:
        go_bin = shutil.which("go")
        if not go_bin:
            self.skipTest("Go toolchain not available")

        env: Dict[str, str] = dict(os.environ)
        env.setdefault("GOTOOLCHAIN", "local")
        env.setdefault("GOFLAGS", "-mod=vendor")

        repo_root = Path(__file__).resolve().parents[2]
        harness_dir = repo_root / "tools" / "mls_harness"

        with tempfile.TemporaryDirectory() as state_dir:
            cmd = [
                go_bin,
                "-C",
                str(harness_dir),
                "run",
                "./cmd/mls-harness",
                "smoke",
                "--iterations",
                "50",
                "--save-every",
                "10",
                "--state-dir",
                state_dir,
            ]
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            if proc.returncode != 0:
                self.fail(
                    f"mls-harness smoke failed with code {proc.returncode}\n"
                    f"stdout:\n{proc.stdout}\n"
                    f"stderr:\n{proc.stderr}\n"
                )


if __name__ == "__main__":
    unittest.main()
