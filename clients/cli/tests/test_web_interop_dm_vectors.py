import base64
import hashlib
import unittest

from cli_app import dm_envelope


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

            env_bytes = base64.b64decode(env_b64, validate=True)
            msg_id_hex = hashlib.sha256(env_bytes).hexdigest()
            self.assertEqual(msg_id_hex, vector["msg_id_hex"])


if __name__ == "__main__":
    unittest.main()
