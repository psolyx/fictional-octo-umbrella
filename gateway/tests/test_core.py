import unittest

from gateway.cursors import CursorStore
from gateway.hub import SubscriptionHub
from gateway.log import ConversationLog


class TestConversationLog(unittest.TestCase):
    def test_seq_increments_per_conversation(self):
        log = ConversationLog()

        s1, e1 = log.append("c1", "m1", "a", "d1", 1)
        s2, e2 = log.append("c1", "m2", "b", "d2", 2)
        s3, e3 = log.append("c2", "m1", "c", "d3", 3)

        self.assertEqual((s1, e1.seq), (1, 1))
        self.assertEqual((s2, e2.seq), (2, 2))
        self.assertEqual((s3, e3.seq), (1, 1))

    def test_idempotent_append_returns_original_event(self):
        log = ConversationLog()

        first_seq, first_event = log.append("c1", "m1", b"payload", "d1", 10)
        repeat_seq, repeat_event = log.append("c1", "m1", b"payload", "d2", 20)

        self.assertEqual(first_seq, 1)
        self.assertEqual(repeat_seq, 1)
        self.assertIs(first_event, repeat_event)

    def test_list_since_orders_and_limits(self):
        log = ConversationLog()
        for i in range(5):
            log.append("c1", f"m{i}", str(i), "d1", i)

        window = log.list_since("c1", after_seq=2, limit=2)
        self.assertEqual([e.seq for e in window], [3, 4])


class TestCursorStore(unittest.TestCase):
    def test_ack_monotonicity(self):
        cursors = CursorStore()

        cursors.ack("d1", "c1", 2)
        with self.assertRaises(ValueError):
            cursors.ack("d1", "c1", 1)
        self.assertEqual(cursors.last_ack("d1", "c1"), 2)


class TestSubscriptionHub(unittest.TestCase):
    def test_echo_to_sender(self):
        hub = SubscriptionHub()
        log = ConversationLog()
        events = []

        def capture(event):
            events.append(event.seq)

        hub.subscribe("d1", "c1", capture)
        _, event = log.append("c1", "m1", "payload", "d1", 1)
        hub.broadcast(event)

        self.assertEqual(events, [1])


if __name__ == "__main__":
    unittest.main()
