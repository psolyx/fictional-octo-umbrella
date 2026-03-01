import os
import pathlib
import subprocess
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestPhase52SignoffArchiveContracts(unittest.TestCase):
    def test_bundle_dry_run_includes_archive_plan_by_default(self):
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
        self.assertIn("step=a1 plan deterministic_signoff_archive", proc.stdout)

    def test_bundle_dry_run_skips_archive_plan_when_opted_out(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "clients/cli/src"
        env["SIGNOFF_DRY_RUN"] = "1"
        env["SIGNOFF_NO_ARCHIVE"] = "1"
        proc = subprocess.run(
            ["python", "-m", "cli_app.phase5_2_signoff_bundle_main"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode)
        self.assertNotIn("step=a1 plan deterministic_signoff_archive", proc.stdout)

    def test_verify_dry_run_with_archive_path_reports_archive_mode(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "clients/cli/src"
        env["VERIFY_DRY_RUN"] = "1"
        env["ARCHIVE_PATH"] = "dummy.tgz"
        proc = subprocess.run(
            ["python", "-m", "cli_app.phase5_2_signoff_verify_main"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode)
        self.assertIn("mode=archive", proc.stdout)
        self.assertIn("mode=dir", proc.stdout)


if __name__ == "__main__":
    unittest.main()
