import json
import tempfile
import unittest
from pathlib import Path

from cli_app import dm_envelope, mls_poc
from cli_app.interop_transcript import (
    canonicalize_transcript,
    compute_digest_sha256_b64,
    compute_msg_id_hex,
    decode_env_kind,
)


class WebInteropTranscriptVectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]
        self.vector_paths = [
            self.repo_root / "clients" / "web" / "vectors" / "interop_transcript_smoke_v1.json",
            self.repo_root / "clients" / "web" / "vectors" / "interop_transcript_seeded_smoke_v2.json",
        ]

    def _load_vector(self, vector_path: Path) -> dict:
        with vector_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _canonicalize_vector(self, vector: dict) -> dict:
        return canonicalize_transcript(
            vector["conv_id"],
            vector["from_seq"],
            vector["next_seq"],
            vector["events"],
        )

    def _assert_required_types(self, vector: dict) -> None:
        self.assertIn("schema_version", vector)
        self.assertIn("conv_id", vector)
        self.assertIn("from_seq", vector)
        self.assertIn("next_seq", vector)
        self.assertIn("events", vector)
        self.assertIn("digest_sha256_b64", vector)

        self.assertIsInstance(vector["schema_version"], int)
        self.assertIsInstance(vector["conv_id"], str)
        self.assertIsInstance(vector["from_seq"], int)
        self.assertIsInstance(vector["next_seq"], int)
        self.assertIsInstance(vector["events"], list)
        self.assertIsInstance(vector["digest_sha256_b64"], str)

    def test_web_interop_transcript_vector_digest(self) -> None:
        for vector_path in self.vector_paths:
            with self.subTest(vector=vector_path.name):
                vector = self._load_vector(vector_path)
                self._assert_required_types(vector)

                canonical = self._canonicalize_vector(vector)
                digest_b64 = compute_digest_sha256_b64(canonical)

                self.assertEqual(digest_b64, vector["digest_sha256_b64"])
                self.assertEqual(canonical["schema_version"], vector["schema_version"])
                self.assertEqual(canonical["conv_id"], vector["conv_id"])
                self.assertEqual(canonical["from_seq"], vector["from_seq"])
                self.assertEqual(canonical["next_seq"], vector["next_seq"])
                self.assertEqual(len(canonical["events"]), len(vector["events"]))

    def test_events_validate_env_kind_and_msg_id(self) -> None:
        for vector_path in self.vector_paths:
            with self.subTest(vector=vector_path.name):
                vector = self._load_vector(vector_path)
                events = vector["events"]
                seen_seqs = set()
                expected_kinds = {1: 1, 2: 2, 3: 3}

                for event in events:
                    seq = event.get("seq")
                    env = event.get("env")
                    msg_id = event.get("msg_id")

                    self.assertIsInstance(seq, int)
                    self.assertGreaterEqual(seq, 1)
                    self.assertNotIn(seq, seen_seqs)
                    seen_seqs.add(seq)

                    self.assertIsInstance(env, str)
                    self.assertIsInstance(msg_id, str)

                    kind = decode_env_kind(env)
                    self.assertEqual(kind, expected_kinds.get(seq))

                    recomputed_msg_id = compute_msg_id_hex(env)
                    self.assertEqual(recomputed_msg_id, msg_id)

                self.assertEqual(seen_seqs, {1, 2, 3})

    def test_canonical_events_are_sorted_and_stable(self) -> None:
        for vector_path in self.vector_paths:
            with self.subTest(vector=vector_path.name):
                vector = self._load_vector(vector_path)
                canonical = self._canonicalize_vector(vector)

                seqs = [event["seq"] for event in canonical["events"]]
                self.assertEqual(seqs, sorted(seqs))
                for event in canonical["events"]:
                    self.assertEqual(set(event.keys()), {"seq", "msg_id", "env"})
                    self.assertIsInstance(event["seq"], int)
                    self.assertIsInstance(event["env"], str)
                    self.assertIsInstance(event["msg_id"], str)

    def test_event_order_does_not_change_digest(self) -> None:
        for vector_path in self.vector_paths:
            with self.subTest(vector=vector_path.name):
                vector = self._load_vector(vector_path)
                events = vector["events"]

                reversed_events = list(reversed(events))
                canonical_reversed = canonicalize_transcript(
                    vector["conv_id"],
                    vector["from_seq"],
                    vector["next_seq"],
                    reversed_events,
                )
                digest_reversed = compute_digest_sha256_b64(canonical_reversed)

                canonical_forward = canonicalize_transcript(
                    vector["conv_id"],
                    vector["from_seq"],
                    vector["next_seq"],
                    events,
                )
                digest_forward = compute_digest_sha256_b64(canonical_forward)

                self.assertEqual(digest_reversed, vector["digest_sha256_b64"])
                self.assertEqual(digest_forward, vector["digest_sha256_b64"])

    def test_unknown_event_fields_are_ignored(self) -> None:
        for vector_path in self.vector_paths:
            with self.subTest(vector=vector_path.name):
                vector = self._load_vector(vector_path)
                events = [dict(event, extra_field="ignore") for event in vector["events"]]

                canonical = canonicalize_transcript(
                    vector["conv_id"],
                    vector["from_seq"],
                    vector["next_seq"],
                    events,
                )
                digest_b64 = compute_digest_sha256_b64(canonical)

                for event in canonical["events"]:
                    self.assertEqual(set(event.keys()), {"seq", "msg_id", "env"})

                self.assertEqual(digest_b64, vector["digest_sha256_b64"])

    def test_invalid_events_are_filtered_before_digest(self) -> None:
        for vector_path in self.vector_paths:
            with self.subTest(vector=vector_path.name):
                vector = self._load_vector(vector_path)
                events = list(vector["events"])
                events.extend(
                    [
                        "not-a-dict",
                        {"seq": "3", "env": "AQ==", "msg_id": "skip"},
                        {"seq": 9, "env": 123, "msg_id": "skip"},
                    ]
                )

                canonical = canonicalize_transcript(
                    vector["conv_id"],
                    vector["from_seq"],
                    vector["next_seq"],
                    events,
                )
                digest_b64 = compute_digest_sha256_b64(canonical)

                self.assertEqual(len(canonical["events"]), len(vector["events"]))
                self.assertEqual(digest_b64, vector["digest_sha256_b64"])

    def test_seeded_transcript_app_env_decrypts(self) -> None:
        seeded_vector_path = (
            self.repo_root
            / "clients"
            / "web"
            / "vectors"
            / "interop_transcript_seeded_smoke_v2.json"
        )
        dm_seeded_vector_path = (
            self.repo_root
            / "clients"
            / "web"
            / "vectors"
            / "dm_seeded_welcome_commit_v1.json"
        )
        seeded_vector = self._load_vector(seeded_vector_path)
        dm_seeded_vector = self._load_vector(dm_seeded_vector_path)
        seeds = dm_seeded_vector["seeds"]
        group_id_b64 = dm_seeded_vector["group_id_b64"]

        app_event = next(event for event in seeded_vector["events"] if event.get("seq") == 3)
        app_kind, app_payload_b64 = dm_envelope.unpack(app_event["env"])
        self.assertEqual(app_kind, 0x03)

        with tempfile.TemporaryDirectory() as initiator_dir, tempfile.TemporaryDirectory() as joiner_dir:
            initiator_kp = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-keypackage",
                    [
                        "--state-dir",
                        initiator_dir,
                        "--name",
                        "initiator",
                        "--seed",
                        str(seeds["initiator_keypackage_seed"]),
                    ],
                )
            )
            joiner_kp = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-keypackage",
                    [
                        "--state-dir",
                        joiner_dir,
                        "--name",
                        "joiner",
                        "--seed",
                        str(seeds["joiner_keypackage_seed"]),
                    ],
                )
            )
            dm_init_output = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-init",
                    [
                        "--state-dir",
                        initiator_dir,
                        "--peer-keypackage",
                        joiner_kp,
                        "--group-id",
                        group_id_b64,
                        "--seed",
                        str(seeds["dm_init_seed"]),
                    ],
                )
            )
            init_payload = json.loads(dm_init_output)
            welcome_payload_b64 = init_payload["welcome"]
            commit_payload_b64 = init_payload["commit"]

            mls_poc._run_harness_capture(
                "dm-join",
                [
                    "--state-dir",
                    joiner_dir,
                    "--welcome",
                    welcome_payload_b64,
                ],
            )
            mls_poc._run_harness_capture(
                "dm-commit-apply",
                [
                    "--state-dir",
                    initiator_dir,
                    "--commit",
                    commit_payload_b64,
                ],
            )
            mls_poc._run_harness_capture(
                "dm-commit-apply",
                [
                    "--state-dir",
                    joiner_dir,
                    "--commit",
                    commit_payload_b64,
                ],
            )

            decrypted = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-decrypt",
                    [
                        "--state-dir",
                        joiner_dir,
                        "--ciphertext",
                        app_payload_b64,
                    ],
                )
            )
            self.assertEqual(decrypted, "phase5-seeded-transcript")


if __name__ == "__main__":
    unittest.main()
