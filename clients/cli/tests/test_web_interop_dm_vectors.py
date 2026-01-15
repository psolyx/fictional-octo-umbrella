import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cli_app import dm_envelope, mls_poc


def _load_seeded_vector() -> dict:
    repo_root = mls_poc.find_repo_root()
    vector_path = repo_root / "clients" / "web" / "vectors" / "dm_seeded_welcome_commit_v1.json"
    with vector_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _decode_env(env_b64: str) -> bytes:
    return base64.b64decode(env_b64, validate=True)


def _msg_id_for_env(env_bytes: bytes) -> str:
    return hashlib.sha256(env_bytes).hexdigest()


def _first_line(output: str) -> str:
    return mls_poc._first_nonempty_line(output)


def _assert_env_matches(test_case: unittest.TestCase, env_b64: str, kind: int, msg_id_hex: str) -> bytes:
    env_bytes = _decode_env(env_b64)
    test_case.assertGreater(len(env_bytes), 1)
    test_case.assertEqual(env_bytes[0], kind)
    test_case.assertEqual(_msg_id_for_env(env_bytes), msg_id_hex)
    return env_bytes


class WebInteropDmVectorTests(unittest.TestCase):
    def test_web_interop_vectors(self):
        vectors = [
            {
                "kind": 1,
                "payload_bytes": b"",
                "payload_b64": "",
                "env_b64": "AQ==",
                "msg_id_hex": "4bf5122f344554c53bde2ebb8cd2b7e3d1600ad631c385a5d7cce23c7785459a",
            },
            {
                "kind": 2,
                "payload_bytes": b"\x00\x01\x02\x03\xff",
                "payload_b64": "AAECA/8=",
                "env_b64": "AgABAgP/",
                "msg_id_hex": "2d24137c6e004c092e2f83656f77180ee1c38ac9379b7d3c78064b7ac5bf9bed",
            },
            {
                "kind": 3,
                "payload_bytes": b"hello, world",
                "payload_b64": "aGVsbG8sIHdvcmxk",
                "env_b64": "A2hlbGxvLCB3b3JsZA==",
                "msg_id_hex": "279906f48ff704cb11417bf5d4e6546a0492894135bb6f173d8d433e6cbbcf93",
            },
        ]

        for vector in vectors:
            payload_b64 = base64.b64encode(vector["payload_bytes"]).decode("utf-8")
            self.assertEqual(payload_b64, vector["payload_b64"])

            env_b64 = dm_envelope.pack(vector["kind"], payload_b64)
            self.assertEqual(env_b64, vector["env_b64"])

            kind_out, payload_out = dm_envelope.unpack(env_b64)
            self.assertEqual(kind_out, vector["kind"])
            self.assertEqual(payload_out, payload_b64)

            env_bytes = _decode_env(env_b64)
            msg_id_hex = _msg_id_for_env(env_bytes)
            self.assertEqual(msg_id_hex, vector["msg_id_hex"])

    def test_seeded_dm_welcome_commit_vector(self):
        vector = _load_seeded_vector()
        self.assertEqual(vector["name"], "dm_seeded_welcome_commit_v1")

        seeds = vector["seeds"]
        group_id_b64 = vector["group_id_b64"]

        self.assertEqual(base64.b64decode(group_id_b64, validate=True), b"dm-group")
        self.assertEqual(
            set(seeds.keys()),
            {"initiator_keypackage_seed", "joiner_keypackage_seed", "dm_init_seed"},
        )
        for seed_value in seeds.values():
            self.assertIsInstance(seed_value, int)
            self.assertGreater(seed_value, 0)

        _assert_env_matches(self, vector["welcome_env_b64"], 0x01, vector["welcome_msg_id_hex"])
        _assert_env_matches(self, vector["commit_env_b64"], 0x02, vector["commit_msg_id_hex"])

        with tempfile.TemporaryDirectory() as initiator_dir, tempfile.TemporaryDirectory() as joiner_dir:
            initiator_kp = _first_line(
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
            self.assertTrue(initiator_kp)
            joiner_kp = _first_line(
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
            self.assertTrue(joiner_kp)
            self.assertNotEqual(initiator_kp, joiner_kp)

            dm_init_output = _first_line(
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
            payload = json.loads(dm_init_output)
            welcome_payload_b64 = payload["welcome"]
            commit_payload_b64 = payload["commit"]
            self.assertTrue(welcome_payload_b64)
            self.assertTrue(commit_payload_b64)

            recomputed_welcome_env = dm_envelope.pack(0x01, welcome_payload_b64)
            recomputed_commit_env = dm_envelope.pack(0x02, commit_payload_b64)
            self.assertEqual(recomputed_welcome_env, vector["welcome_env_b64"])
            self.assertEqual(recomputed_commit_env, vector["commit_env_b64"])
            self.assertEqual(
                _msg_id_for_env(_decode_env(recomputed_welcome_env)),
                vector["welcome_msg_id_hex"],
            )
            self.assertEqual(
                _msg_id_for_env(_decode_env(recomputed_commit_env)),
                vector["commit_msg_id_hex"],
            )

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

            plaintext = "phase5-seeded-smoke"
            ciphertext_b64 = _first_line(
                mls_poc._run_harness_capture(
                    "dm-encrypt",
                    [
                        "--state-dir",
                        initiator_dir,
                        "--plaintext",
                        plaintext,
                    ],
                )
            )
            self.assertTrue(ciphertext_b64)
            self.assertNotEqual(ciphertext_b64, plaintext)
            decrypted = _first_line(
                mls_poc._run_harness_capture(
                    "dm-decrypt",
                    [
                        "--state-dir",
                        joiner_dir,
                        "--ciphertext",
                        ciphertext_b64,
                    ],
                )
            )
            self.assertEqual(decrypted, plaintext)


if __name__ == "__main__":
    unittest.main()
