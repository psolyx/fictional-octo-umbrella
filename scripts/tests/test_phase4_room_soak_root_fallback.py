import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class Phase4RoomSoakRootFallbackTest(unittest.TestCase):
    @unittest.skipUnless(os.getenv("RUN_SCRIPT_TESTS") == "1", "set RUN_SCRIPT_TESTS=1 to enable script integration tests")
    def test_runs_without_git_directory(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="phase4_soak_copy_") as tmp:
            copied_repo = Path(tmp) / "repo"
            shutil.copytree(repo_root, copied_repo, ignore=shutil.ignore_patterns(".git"))
            script_path = copied_repo / "scripts" / "phase4_room_soak.sh"
            mode = script_path.stat().st_mode
            script_path.chmod(mode | stat.S_IXUSR)

            out_dir = Path(tmp) / "soak_out"
            proc = subprocess.run(
                [str(script_path), "1", "1", "2", str(out_dir)],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PASTE BEGIN", proc.stdout)
        self.assertIn("PASTE END", proc.stdout)
        self.assertEqual(proc.stdout.count("PASTE BEGIN"), 1)
        self.assertEqual(proc.stdout.count("PASTE END"), 1)
        self.assertIn("git rev-parse failed; falling back to script-relative root.", proc.stderr)


if __name__ == "__main__":
    unittest.main()
