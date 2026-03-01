import os
import pathlib
import subprocess
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestPhase52SignoffBundleContracts(unittest.TestCase):
    def test_dry_run_markers_and_deterministic_lines(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "clients/cli/src"
        env["SIGNOFF_DRY_RUN"] = "1"
        proc = subprocess.run(
            ["python", "-m", "cli_app.phase5_2_signoff_bundle_main"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        self.assertIn("PHASE5_2_SIGNOFF_BUNDLE_BEGIN", lines)
        self.assertIn("PHASE5_2_SIGNOFF_BUNDLE_V1", lines)
        self.assertIn("PHASE5_2_SIGNOFF_BUNDLE_END", lines)
        expected_lines = [
            "PHASE5_2_SIGNOFF_BUNDLE_BEGIN",
            "PHASE5_2_SIGNOFF_BUNDLE_V1",
            "step=t01 plan gateway_test_social_profile_and_feed",
            "step=t13 plan phase5_browser_wasm_cli_coexist_smoke",
            "step=s1 plan phase5_2_smoke_lite_main",
            "step=s2 plan phase5_2_static_audit_main",
            "PHASE5_2_SIGNOFF_BUNDLE_OK",
            "PHASE5_2_SIGNOFF_BUNDLE_END",
        ]
        for expected in expected_lines:
            self.assertIn(expected, lines)


if __name__ == "__main__":
    unittest.main()
