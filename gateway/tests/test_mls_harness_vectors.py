import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Dict, Optional, Tuple


class TestMLSHarnessVectors(unittest.TestCase):
    def _parse_go_version(self, raw: str) -> Optional[Tuple[int, int, int]]:
        match = re.search(r"go(\d+)\.(\d+)(?:\.(\d+))?", raw)
        if not match:
            return None

        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch or 0)

    def _get_go_version(self, go_bin: str) -> Optional[Tuple[int, int, int]]:
        for args in ([go_bin, "env", "GOVERSION"], [go_bin, "version"]):
            try:
                output = subprocess.check_output(args, text=True).strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

            parsed = self._parse_go_version(output)
            if parsed:
                return parsed

        return None

    def test_vectors_digest_matches(self) -> None:
        go_bin = shutil.which("go")
        if not go_bin:
            self.skipTest("Go toolchain not available")

        go_version = self._get_go_version(go_bin)
        if not go_version:
            self.skipTest("Unable to determine Go version")

        if go_version < (1, 22, 0):
            self.skipTest("Go >= 1.22 required for MLS harness vectors test")

        env: Dict[str, str] = dict(os.environ)
        env.setdefault("GOTOOLCHAIN", "local")
        env.setdefault("GOFLAGS", "-mod=vendor")

        repo_root = Path(__file__).resolve().parents[2]
        harness_dir = repo_root / "tools" / "mls_harness"

        cmd = [
            go_bin,
            "run",
            "./cmd/mls-harness",
            "vectors",
            "--vector-file",
            "./vectors/dm_smoke_v1.json",
        ]
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            cwd=harness_dir,
            env=env,
        )

        if proc.returncode != 0:
            self.fail(
                f"mls-harness vectors failed with code {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}\n"
            )


if __name__ == "__main__":
    unittest.main()
