import os
import pathlib
import hashlib
import subprocess
import tempfile
import unittest

from cli_app.phase5_2_signoff_verify import verify_signoff_bundle


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestPhase52SignoffVerifyContracts(unittest.TestCase):
    def test_dry_run_markers_and_plan_lines(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = "clients/cli/src"
        env["VERIFY_DRY_RUN"] = "1"
        proc = subprocess.run(
            ["python", "-m", "cli_app.phase5_2_signoff_verify_main"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        for marker in (
            "PHASE5_2_SIGNOFF_VERIFY_BEGIN",
            "PHASE5_2_SIGNOFF_VERIFY_V1",
            "PHASE5_2_SIGNOFF_VERIFY_OK",
            "PHASE5_2_SIGNOFF_VERIFY_END",
        ):
            self.assertIn(marker, lines)
        expected_plan = [
            "mode=archive",
            "plan validate archive extension and sibling sha256",
            "plan validate archive sha256 strict single-line format",
            "plan safe extract archive and delegate directory verification",
            "mode=dir",
            "plan validate required files",
            "plan validate summary markers against manifest success",
            "plan validate sha256 strict ordering and integrity",
            "plan validate manifest structure and status consistency",
            "plan validate redaction forbidden token scan",
        ]
        for plan_line in expected_plan:
            self.assertIn(plan_line, lines)
        for line in lines:
            self.assertNotRegex(line, r"\d{4}-\d{2}-\d{2}")
            self.assertNotRegex(line, r"\d{2}:\d{2}:\d{2}")

    def test_verify_accepts_redacted_transcript_tokens(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = pathlib.Path(temp_dir)
            gate_dir = bundle / "GATE_TESTS"
            gate_dir.mkdir(parents=True, exist_ok=True)

            files: dict[str, str] = {
                "SIGNOFF_SUMMARY.txt": "PHASE5_2_SIGNOFF_BUNDLE_BEGIN\nPHASE5_2_SIGNOFF_BUNDLE_OK\nPHASE5_2_SIGNOFF_BUNDLE_END\n",
                "ENV.txt": "auth_token=[REDACTED]\nresume_token=[REDACTED]\n",
                "MANIFEST.json": (
                    '{\n'
                    '  "bundle_version": "PHASE5_2_SIGNOFF_BUNDLE_V1",\n'
                    '  "created_utc": "20260101T000000Z",\n'
                    '  "steps": [\n'
                    '    {"duration_s": 0.1, "exit_code": 0, "label": "ok", "output": "GATE_TESTS/t01_gateway_test_social_profile_and_feed.txt", "status": "PASS", "step_id": "t01"}\n'
                    '  ],\n'
                    '  "success": true\n'
                    '}\n'
                ),
                "PHASE5_2_SMOKE_LITE.txt": "Authorization: Bearer [REDACTED]\n",
                "PHASE5_2_STATIC_AUDIT.txt": "ok\n",
                "GATEWAY_SERVER.txt": "ok\n",
                "index.html": "<html><body>ok</body></html>\n",
            }
            gate_names = [
                "t01_gateway_test_social_profile_and_feed.txt",
                "t02_gateway_test_retention_gc.txt",
                "t03_gateway_test_conversation_list.txt",
                "t04_gateway_test_rooms_roles.txt",
                "t05_gateway_test_presence.txt",
                "t06_gateway_test_abuse_controls.txt",
                "t07_cli_test_web_ui_contracts.txt",
                "t08_cli_test_roadmap_spec_contracts.txt",
                "t09_tui_social_profile_contracts.txt",
                "t10_tui_account_contracts.txt",
                "t11_tui_rooms_contracts.txt",
                "t12_phase5_browser_runtime_smoke.txt",
                "t13_phase5_browser_wasm_cli_coexist_smoke.txt",
            ]
            for gate in gate_names:
                files[f"GATE_TESTS/{gate}"] = "ok\n"
            for rel, content in files.items():
                path = bundle / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            hashed = sorted(
                rel for rel in files.keys() if rel != "sha256.txt"
            )
            with (bundle / "sha256.txt").open("w", encoding="utf-8", newline="\n") as handle:
                for rel in hashed:
                    digest = hashlib.sha256((bundle / rel).read_bytes()).hexdigest()
                    handle.write(f"{digest}  {rel}\n")

            rc = verify_signoff_bundle(str(bundle), out=os.sys.stdout)
            self.assertEqual(0, rc)


if __name__ == "__main__":
    unittest.main()
