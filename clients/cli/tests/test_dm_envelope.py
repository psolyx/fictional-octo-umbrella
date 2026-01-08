import base64
import unittest

from cli_app import dm_envelope


class DmEnvelopeTests(unittest.TestCase):
    def test_pack_unpack_roundtrip(self):
        payload = base64.b64encode(b"hello").decode("utf-8")
        env_b64 = dm_envelope.pack(0x01, payload)
        kind, payload_out = dm_envelope.unpack(env_b64)
        self.assertEqual(kind, 0x01)
        self.assertEqual(payload_out, payload)

    def test_pack_rejects_invalid_inputs(self):
        payload = base64.b64encode(b"hello").decode("utf-8")
        with self.assertRaises(dm_envelope.EnvelopeError):
            dm_envelope.pack(-1, payload)
        with self.assertRaises(dm_envelope.EnvelopeError):
            dm_envelope.pack(256, payload)
        with self.assertRaises(dm_envelope.EnvelopeError):
            dm_envelope.pack(1, "not-base64")

    def test_unpack_rejects_invalid_env(self):
        with self.assertRaises(dm_envelope.EnvelopeError):
            dm_envelope.unpack("not-base64")
        with self.assertRaises(dm_envelope.EnvelopeError):
            dm_envelope.unpack("")


if __name__ == "__main__":
    unittest.main()
