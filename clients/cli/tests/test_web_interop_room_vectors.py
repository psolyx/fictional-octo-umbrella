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


class WebInteropRoomVectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]
        self.vector_path = (
            self.repo_root / "clients" / "web" / "vectors" / "room_seeded_bootstrap_v1.json"
        )

    def _load_vector(self) -> dict:
        with self.vector_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _canonicalize_vector(self, vector: dict) -> dict:
        return canonicalize_transcript(
            vector["conv_id"],
            vector["from_seq"],
            vector["next_seq"],
            vector["events"],
        )

    def test_room_transcript_vector_digest(self) -> None:
        vector = self._load_vector()
        canonical = self._canonicalize_vector(vector)
        digest_b64 = compute_digest_sha256_b64(canonical)

        self.assertEqual(digest_b64, vector["digest_sha256_b64"])
        self.assertEqual(canonical["schema_version"], vector["schema_version"])
        self.assertEqual(canonical["conv_id"], vector["conv_id"])
        self.assertEqual(canonical["from_seq"], vector["from_seq"])
        self.assertEqual(canonical["next_seq"], vector["next_seq"])
        self.assertEqual(len(canonical["events"]), len(vector["events"]))

    def test_room_events_validate_env_kind_and_msg_id(self) -> None:
        vector = self._load_vector()
        events = vector["events"]
        expected_kinds = {1: 1, 2: 2, 3: 3, 4: 1, 5: 2}
        seen_seqs = set()

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

        self.assertEqual(seen_seqs, {1, 2, 3, 4, 5})

    def test_seeded_room_app_env_decrypts(self) -> None:
        vector = self._load_vector()
        seeds = vector["seeds"]
        group_id_b64 = vector["group_id_b64"]
        app_plaintext = vector["app_plaintext"]
        events_by_seq = {event["seq"]: event for event in vector["events"]}

        app_event = events_by_seq[3]
        app_kind, app_payload_b64 = dm_envelope.unpack(app_event["env"])
        self.assertEqual(app_kind, 0x03)

        with tempfile.TemporaryDirectory() as owner_dir, tempfile.TemporaryDirectory() as peer_one_dir, tempfile.TemporaryDirectory() as peer_two_dir:
            owner_kp = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-keypackage",
                    [
                        "--state-dir",
                        owner_dir,
                        "--name",
                        "owner",
                        "--seed",
                        str(seeds["owner_keypackage_seed"]),
                    ],
                )
            )
            peer_one_kp = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-keypackage",
                    [
                        "--state-dir",
                        peer_one_dir,
                        "--name",
                        "peer_one",
                        "--seed",
                        str(seeds["peer_one_keypackage_seed"]),
                    ],
                )
            )
            peer_two_kp = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-keypackage",
                    [
                        "--state-dir",
                        peer_two_dir,
                        "--name",
                        "peer_two",
                        "--seed",
                        str(seeds["peer_two_keypackage_seed"]),
                    ],
                )
            )

            group_init_output = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "group-init",
                    [
                        "--state-dir",
                        owner_dir,
                        "--peer-keypackage",
                        peer_one_kp,
                        "--peer-keypackage",
                        peer_two_kp,
                        "--group-id",
                        group_id_b64,
                        "--seed",
                        str(seeds["group_init_seed"]),
                    ],
                )
            )
            init_payload = json.loads(group_init_output)
            init_welcome_b64 = init_payload["welcome"]
            init_commit_b64 = init_payload["commit"]

            init_welcome_env = dm_envelope.pack(0x01, init_welcome_b64)
            init_commit_env = dm_envelope.pack(0x02, init_commit_b64)
            self.assertEqual(init_welcome_env, events_by_seq[1]["env"])
            self.assertEqual(init_commit_env, events_by_seq[2]["env"])

            mls_poc._run_harness_capture(
                "dm-join",
                [
                    "--state-dir",
                    peer_one_dir,
                    "--welcome",
                    init_welcome_b64,
                ],
            )
            mls_poc._run_harness_capture(
                "dm-join",
                [
                    "--state-dir",
                    peer_two_dir,
                    "--welcome",
                    init_welcome_b64,
                ],
            )

            for state_dir in (owner_dir, peer_one_dir, peer_two_dir):
                mls_poc._run_harness_capture(
                    "dm-commit-apply",
                    [
                        "--state-dir",
                        state_dir,
                        "--commit",
                        init_commit_b64,
                    ],
                )

            decrypted = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-decrypt",
                    [
                        "--state-dir",
                        peer_two_dir,
                        "--ciphertext",
                        app_payload_b64,
                    ],
                )
            )
            self.assertEqual(decrypted, app_plaintext)

            peer_two_add_kp = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "dm-keypackage",
                    [
                        "--state-dir",
                        peer_two_dir,
                        "--name",
                        "peer_two",
                        "--seed",
                        str(seeds["peer_two_add_keypackage_seed"]),
                    ],
                )
            )
            group_add_output = mls_poc._first_nonempty_line(
                mls_poc._run_harness_capture(
                    "group-add",
                    [
                        "--state-dir",
                        owner_dir,
                        "--peer-keypackage",
                        peer_two_add_kp,
                        "--seed",
                        str(seeds["group_add_seed"]),
                    ],
                )
            )
            add_payload = json.loads(group_add_output)
            add_welcome_b64 = add_payload["welcome"]
            add_commit_b64 = add_payload["commit"]

            add_welcome_env = dm_envelope.pack(0x01, add_welcome_b64)
            add_commit_env = dm_envelope.pack(0x02, add_commit_b64)
            self.assertEqual(add_welcome_env, events_by_seq[4]["env"])
            self.assertEqual(add_commit_env, events_by_seq[5]["env"])


if __name__ == "__main__":
    unittest.main()
