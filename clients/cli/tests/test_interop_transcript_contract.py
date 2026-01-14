import unittest

from cli_app.interop_transcript import (
    canonicalize_transcript,
    compute_digest_sha256_b64,
    compute_msg_id_hex,
    decode_env_kind,
)


WELCOME_ENV_B64 = "AVdFTENPTUU"
COMMIT_ENV_B64 = "AkNPTU1JVA"
APP_ENV_B64 = "A0FQUERBVEE"

EXPECTED_APP_MSG_ID_HEX = (
    "564dfd2d21a904fc329472c89d1d376fdf45987aa4c77eca1b948a17e6424c8b"
)

EXPECTED_DIGEST_B64 = "bJc0NpwGTpVTb60-xxmw96a7Gpbb2fFz_S1AxkEHI_I"


class InteropTranscriptContractTests(unittest.TestCase):
    def _canonical_payload_fixture(self) -> dict:
        return {
            "schema_version": 1,
            "conv_id": "conv_test",
            "from_seq": 1,
            "next_seq": None,
            "events": [
                {"seq": 1, "msg_id": None, "env": WELCOME_ENV_B64},
                {"seq": 2, "msg_id": "not-a-hex", "env": COMMIT_ENV_B64},
                {"seq": 3, "msg_id": "", "env": APP_ENV_B64},
            ],
        }

    def _mixed_event_fixture(self) -> list:
        return [
            "not-a-dict",
            {"seq": "1", "env": WELCOME_ENV_B64, "msg_id": "bad"},
            {"seq": 2, "env": COMMIT_ENV_B64, "msg_id": 123},
            {"seq": 1, "env": WELCOME_ENV_B64, "msg_id": None},
            {"seq": 3, "env": APP_ENV_B64, "msg_id": ""},
            {"seq": 4, "env": 42, "msg_id": "skip"},
            {"seq": 5, "msg_id": "missing-env"},
            {"seq": 7, "env": COMMIT_ENV_B64, "msg_id": {"oops": True}},
            {"seq": 6, "env": COMMIT_ENV_B64, "msg_id": "not-a-hex"},
        ]

    def test_decode_env_kind_contract(self) -> None:
        """Ensure base64url envs decode to the correct kind byte."""
        fixtures = [
            (WELCOME_ENV_B64, 1),
            (COMMIT_ENV_B64, 2),
            (APP_ENV_B64, 3),
        ]

        for env_b64, expected_kind in fixtures:
            with self.subTest(env_b64=env_b64):
                self.assertEqual(decode_env_kind(env_b64), expected_kind)

    def test_compute_msg_id_hex_contract(self) -> None:
        """The deterministic msg_id contract must not drift."""
        self.assertEqual(compute_msg_id_hex(APP_ENV_B64), EXPECTED_APP_MSG_ID_HEX)
        self.assertNotEqual(compute_msg_id_hex(WELCOME_ENV_B64), EXPECTED_APP_MSG_ID_HEX)

    def test_canonicalize_transcript_contract(self) -> None:
        """Canonicalization must filter + normalize + sort deterministically."""
        events = self._mixed_event_fixture()

        canonical = canonicalize_transcript("conv_test", 1, None, events)
        expected_events = [
            {"seq": 1, "msg_id": None, "env": WELCOME_ENV_B64},
            {"seq": 2, "msg_id": None, "env": COMMIT_ENV_B64},
            {"seq": 3, "msg_id": "", "env": APP_ENV_B64},
            {"seq": 6, "msg_id": "not-a-hex", "env": COMMIT_ENV_B64},
            {"seq": 7, "msg_id": None, "env": COMMIT_ENV_B64},
        ]

        self.assertEqual(canonical["schema_version"], 1)
        self.assertEqual(canonical["conv_id"], "conv_test")
        self.assertEqual(canonical["from_seq"], 1)
        self.assertIsNone(canonical["next_seq"])
        self.assertEqual(canonical["events"], expected_events)
        self.assertEqual(len(canonical["events"]), 5)

        for event in canonical["events"]:
            self.assertIn("seq", event)
            self.assertIn("env", event)
            self.assertIn("msg_id", event)
            self.assertEqual(set(event.keys()), {"seq", "msg_id", "env"})
            self.assertIsInstance(event["seq"], int)
            self.assertIsInstance(event["env"], str)
            if event["msg_id"] is not None:
                self.assertIsInstance(event["msg_id"], str)

    def test_compute_digest_sha256_b64_contract(self) -> None:
        """Digest computation locks down JSON encoding and padding rules."""
        canonical_payload = self._canonical_payload_fixture()

        self.assertEqual(compute_digest_sha256_b64(canonical_payload), EXPECTED_DIGEST_B64)

    def test_digest_matches_canonicalized_fixture(self) -> None:
        """Ensure canonicalize_transcript output remains digest-compatible."""
        events = [
            {"seq": 3, "msg_id": "", "env": APP_ENV_B64},
            {"seq": 1, "msg_id": None, "env": WELCOME_ENV_B64},
            {"seq": 2, "msg_id": "not-a-hex", "env": COMMIT_ENV_B64},
        ]

        canonical = canonicalize_transcript("conv_test", 1, None, events)
        digest_b64 = compute_digest_sha256_b64(canonical)

        self.assertEqual(digest_b64, EXPECTED_DIGEST_B64)
        self.assertEqual(canonical["events"][0]["seq"], 1)
        self.assertEqual(canonical["events"][1]["seq"], 2)
        self.assertEqual(canonical["events"][2]["seq"], 3)
        self.assertIsNone(canonical["events"][0]["msg_id"])
        self.assertEqual(canonical["events"][1]["msg_id"], "not-a-hex")
        self.assertEqual(canonical["events"][2]["msg_id"], "")

    def test_msg_id_contract_for_env_bytes(self) -> None:
        """The deterministic msg_id is the SHA-256 of the env bytes."""
        welcome_msg_id = compute_msg_id_hex(WELCOME_ENV_B64)
        commit_msg_id = compute_msg_id_hex(COMMIT_ENV_B64)
        app_msg_id = compute_msg_id_hex(APP_ENV_B64)

        self.assertEqual(app_msg_id, EXPECTED_APP_MSG_ID_HEX)
        self.assertNotEqual(welcome_msg_id, commit_msg_id)
        self.assertNotEqual(commit_msg_id, app_msg_id)
        self.assertNotEqual(welcome_msg_id, app_msg_id)

    def test_decode_env_kind_rejects_non_str(self) -> None:
        """Non-string env input should be rejected."""
        self.assertIsNone(decode_env_kind(None))
        self.assertIsNone(decode_env_kind(123))
        self.assertIsNone(decode_env_kind({"env": APP_ENV_B64}))

    def test_canonicalize_does_not_mutate_events(self) -> None:
        """The canonicalizer should not mutate caller-owned event dicts."""
        events = [
            {"seq": 2, "env": COMMIT_ENV_B64, "msg_id": 123},
            {"seq": 1, "env": WELCOME_ENV_B64, "msg_id": None},
        ]
        events_snapshot = [dict(item) for item in events]

        canonicalize_transcript("conv_test", 1, None, events)

        self.assertEqual(events, events_snapshot)
        self.assertEqual(events[0]["msg_id"], 123)
        self.assertIsNone(events[1]["msg_id"])

    def test_canonical_payload_fixture_matches_expectations(self) -> None:
        """Freeze the exact canonical payload structure for digest checks."""
        canonical_payload = self._canonical_payload_fixture()

        self.assertEqual(canonical_payload["schema_version"], 1)
        self.assertEqual(canonical_payload["conv_id"], "conv_test")
        self.assertEqual(canonical_payload["from_seq"], 1)
        self.assertIsNone(canonical_payload["next_seq"])
        self.assertEqual(len(canonical_payload["events"]), 3)
        self.assertEqual(canonical_payload["events"][0]["seq"], 1)
        self.assertEqual(canonical_payload["events"][1]["seq"], 2)
        self.assertEqual(canonical_payload["events"][2]["seq"], 3)
        self.assertIsNone(canonical_payload["events"][0]["msg_id"])
        self.assertEqual(canonical_payload["events"][1]["msg_id"], "not-a-hex")
        self.assertEqual(canonical_payload["events"][2]["msg_id"], "")


if __name__ == "__main__":
    unittest.main()
