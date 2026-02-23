import unittest

from cli_app.tui_app import _match_echo_to_pending_entry


class TestTuiMessageLifecycle(unittest.TestCase):
    def test_match_echo_to_pending_by_msg_id(self) -> None:
        transcript = [
            {"dir": "out", "text": "[pending msg_id=a1] hello"},
            {"dir": "in", "text": "peer: ok"},
            {"dir": "out", "text": "[failed msg_id=b2] retry me"},
        ]
        self.assertEqual(_match_echo_to_pending_entry(transcript, "a1"), 0)
        self.assertEqual(_match_echo_to_pending_entry(transcript, "b2"), 2)
        self.assertIsNone(_match_echo_to_pending_entry(transcript, "missing"))


if __name__ == "__main__":
    unittest.main()
