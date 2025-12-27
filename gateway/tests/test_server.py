import io
import json
import unittest

from gateway.server import _load_frames, greet, main, simulate


class TestGatewayServer(unittest.TestCase):
    def test_greet_defaults_to_world(self):
        self.assertEqual(greet(), "Hello, world!")

    def test_greet_strips_whitespace(self):
        self.assertEqual(greet("  Polycentric  "), "Hello, Polycentric!")

    def test_main_writes_output(self):
        buffer = io.StringIO()
        exit_code = main(["team"], output=buffer)

        self.assertEqual(exit_code, 0)
        self.assertEqual(buffer.getvalue().strip(), "Hello, team!")

    def test_load_frames_accepts_array_or_lines(self):
        array_buffer = io.StringIO(json.dumps([{"t": "ping"}]))
        ndjson_buffer = io.StringIO("\n".join(["{\"t\": \"one\"}", "{\"t\": \"two\"}"]))

        self.assertEqual(list(_load_frames(array_buffer)), [{"t": "ping"}])
        self.assertEqual(list(_load_frames(ndjson_buffer)), [{"t": "one"}, {"t": "two"}])

    def test_simulate_streams_events(self):
        frames = [
            {"t": "conv.subscribe", "device_id": "d1", "conv_id": "c1"},
            {
                "t": "conv.send",
                "conv_id": "c1",
                "msg_id": "m1",
                "envelope_b64": "ZXZlbnQ=",
                "sender_device_id": "d1",
                "ts_ms": 1,
            },
        ]
        buffer = io.StringIO()

        simulate(frames, buffer)

        lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["seq"], 1)
        self.assertEqual(lines[0]["device_id"], "d1")


if __name__ == "__main__":
    unittest.main()
