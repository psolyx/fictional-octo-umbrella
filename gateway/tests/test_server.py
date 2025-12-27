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

    def test_replay_defaults_to_cursor(self):
        frames = []
        for i in range(1, 7):
            frames.append(
                {
                    "t": "conv.send",
                    "conv_id": "c1",
                    "msg_id": f"m{i}",
                    "envelope_b64": "ZXZlbnQ=",
                    "sender_device_id": "ds",  # sender doesn't matter here
                    "ts_ms": i,
                }
            )

        frames.extend(
            [
                {"t": "conv.ack", "device_id": "d1", "conv_id": "c1", "seq": 5},
                {"t": "conv.ack", "device_id": "d1", "conv_id": "c1", "seq": 3},
                {"t": "conv.subscribe", "device_id": "d1", "conv_id": "c1"},
                {"t": "conv.replay", "device_id": "d1", "conv_id": "c1"},
            ]
        )

        buffer = io.StringIO()
        simulate(frames, buffer)

        lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
        self.assertEqual([line["seq"] for line in lines], [6])

    def test_replay_from_seq_is_inclusive(self):
        frames = [
            {
                "t": "conv.send",
                "conv_id": "c1",
                "msg_id": "m1",
                "envelope_b64": "ZXZlbnQ=",
                "sender_device_id": "ds",
                "ts_ms": 1,
            },
            {
                "t": "conv.send",
                "conv_id": "c1",
                "msg_id": "m2",
                "envelope_b64": "ZXZlbnQ=",
                "sender_device_id": "ds",
                "ts_ms": 2,
            },
            {"t": "conv.subscribe", "device_id": "d1", "conv_id": "c1"},
            {"t": "conv.replay", "device_id": "d1", "conv_id": "c1", "from_seq": 2},
        ]

        buffer = io.StringIO()
        simulate(frames, buffer)

        lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
        self.assertEqual([line["seq"] for line in lines], [2])

    def test_replay_after_seq_backcompat(self):
        frames = [
            {
                "t": "conv.send",
                "conv_id": "c1",
                "msg_id": "m1",
                "envelope_b64": "ZXZlbnQ=",
                "sender_device_id": "ds",
                "ts_ms": 1,
            },
            {
                "t": "conv.send",
                "conv_id": "c1",
                "msg_id": "m2",
                "envelope_b64": "ZXZlbnQ=",
                "sender_device_id": "ds",
                "ts_ms": 2,
            },
            {
                "t": "conv.send",
                "conv_id": "c1",
                "msg_id": "m3",
                "envelope_b64": "ZXZlbnQ=",
                "sender_device_id": "ds",
                "ts_ms": 3,
            },
            {"t": "conv.subscribe", "device_id": "d1", "conv_id": "c1"},
            {"t": "conv.replay", "device_id": "d1", "conv_id": "c1", "after_seq": 1},
        ]

        buffer = io.StringIO()
        simulate(frames, buffer)

        lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
        self.assertEqual([line["seq"] for line in lines], [2, 3])


if __name__ == "__main__":
    unittest.main()
