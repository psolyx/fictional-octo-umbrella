import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from mls_harness_util import HARNESS_DIR, ensure_harness_binary, make_harness_env, run_harness


class TestMLSHarnessWGVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._harness_bin = ensure_harness_binary(timeout_s=180.0)

    def test_wg_vectors(self) -> None:
        env = make_harness_env()

        proc = run_harness(
            ["wg-vectors", "--vectors-dir", "./vectors/mlswg"],
            harness_bin=self._harness_bin,
            cwd=HARNESS_DIR,
            env=env,
            timeout_s=120.0,
        )

        if proc.returncode != 0:
            self.fail(
                f"mls-harness wg-vectors failed with code {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}\n"
            )


if __name__ == "__main__":
    unittest.main()
