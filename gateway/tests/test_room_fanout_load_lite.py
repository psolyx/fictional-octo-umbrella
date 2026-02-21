import os
from pathlib import Path
import random
import sys
import unittest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gateway as _gateway_pkg

_GATEWAY_SRC_PKG = str(SRC_DIR / "gateway")
if _GATEWAY_SRC_PKG not in _gateway_pkg.__path__:
    _gateway_pkg.__path__.append(_GATEWAY_SRC_PKG)

from gateway.ws_transport import RUNTIME_KEY, _process_conv_send, create_app


def _read_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return int(value)


def _read_float_env(name: str) -> float | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return float(value)


def _clamp(value: int, *, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


class DeviceTracker:
    def __init__(self, runtime, *, device_id: str, conv_id: str) -> None:
        self._runtime = runtime
        self._device_id = device_id
        self._conv_id = conv_id
        self.last_seq = 0
        self.seen: set[int] = set()

    def handle(self, event) -> None:
        seq = event.seq
        if seq in self.seen:
            raise AssertionError(f"duplicate seq {seq} for device {self._device_id}")
        if seq <= self.last_seq:
            raise AssertionError(
                f"out-of-order seq {seq} after {self.last_seq} for device {self._device_id}"
            )
        self.seen.add(seq)
        self.last_seq = seq
        next_seq = self._runtime.cursors.ack(self._device_id, self._conv_id, seq)
        if next_seq != seq + 1:
            raise AssertionError(
                f"cursor did not advance for device {self._device_id}: got {next_seq}, expected {seq + 1}"
            )


class RoomFanoutLoadLiteTests(unittest.TestCase):
    def test_room_fanout_offline_churn_and_replay(self) -> None:
        app = create_app(ping_interval_s=3600)
        runtime = app[RUNTIME_KEY]

        run_slow = os.getenv("RUN_SLOW_TESTS") == "1"
        run_soak = os.getenv("RUN_SOAK_TESTS") == "1"

        default_member_count = 900 if run_slow else 200
        default_message_count = 300 if run_slow else 120

        requested_member_count = _read_int_env("ROOM_MEMBERS")
        requested_duration_s = _read_int_env("ROOM_DURATION_S")
        requested_message_count = _read_int_env("ROOM_MSG_COUNT")
        requested_message_rate = _read_float_env("ROOM_MSG_RATE")

        if requested_message_count is None and requested_message_rate is not None:
            duration_for_rate = (
                requested_duration_s if requested_duration_s is not None else 60
            )
            requested_message_count = int(round(requested_message_rate * duration_for_rate))

        member_count = (
            requested_member_count
            if requested_member_count is not None
            else default_member_count
        )
        message_count = (
            requested_message_count
            if requested_message_count is not None
            else default_message_count
        )

        if not run_soak:
            member_count = _clamp(member_count, lower=2, upper=200)
            message_count = _clamp(message_count, lower=1, upper=120)

        conv_id = "room-load-lite"
        members = [f"user-{i}" for i in range(member_count)]
        owner_user_id = members[0]
        runtime.conversations.create(
            conv_id,
            owner_user_id,
            members[1:],
            home_gateway=runtime.gateway_id,
        )

        trackers: dict[str, DeviceTracker] = {}
        subscriptions = {}
        sessions = []
        for index, user_id in enumerate(members):
            device_id = f"device-{index}"
            session = runtime.sessions.create(user_id, device_id)
            sessions.append(session)
            tracker = DeviceTracker(runtime, device_id=device_id, conv_id=conv_id)
            trackers[device_id] = tracker
            subscriptions[device_id] = runtime.hub.subscribe(
                device_id, conv_id, tracker.handle
            )

        rng = random.Random(1337)
        last_seq = 0

        for msg_index in range(1, message_count // 2 + 1):
            sender = rng.choice(sessions)
            seq, event, error = _process_conv_send(
                runtime,
                sender,
                {
                    "conv_id": conv_id,
                    "msg_id": f"m{msg_index}",
                    "env": "ZW4=",
                    "ts": msg_index,
                },
            )
            self.assertIsNone(error)
            self.assertIsNotNone(event)
            self.assertEqual(seq, last_seq + 1)
            last_seq = seq or last_seq

        offline_candidates = [f"device-{i}" for i in range(1, member_count)]
        offline_count = max(1, int(member_count * 0.2))
        offline_devices = set(rng.sample(offline_candidates, offline_count))
        for device_id in offline_devices:
            runtime.hub.unsubscribe(subscriptions[device_id])

        for msg_index in range(message_count // 2 + 1, message_count + 1):
            sender = rng.choice(sessions)
            seq, event, error = _process_conv_send(
                runtime,
                sender,
                {
                    "conv_id": conv_id,
                    "msg_id": f"m{msg_index}",
                    "env": "ZW4=",
                    "ts": msg_index,
                },
            )
            self.assertIsNone(error)
            self.assertIsNotNone(event)
            self.assertEqual(seq, last_seq + 1)
            last_seq = seq or last_seq

        for device_id in offline_devices:
            tracker = trackers[device_id]
            subscriptions[device_id] = runtime.hub.subscribe(
                device_id, conv_id, tracker.handle
            )
            from_seq = runtime.cursors.next_seq(device_id, conv_id)
            events = runtime.log.list_from(conv_id, from_seq)
            for event in events:
                tracker.handle(event)
            self.assertEqual(tracker.last_seq, last_seq)
            self.assertEqual(runtime.cursors.next_seq(device_id, conv_id), last_seq + 1)

        target_user_id = members[1]
        target_session = next(
            session for session in sessions if session.user_id == target_user_id
        )
        runtime.conversations.remove(conv_id, owner_user_id, [target_user_id])
        seq, event, error = _process_conv_send(
            runtime,
            target_session,
            {
                "conv_id": conv_id,
                "msg_id": "blocked-send",
                "env": "ZW4=",
                "ts": message_count + 1,
            },
        )
        self.assertIsNone(seq)
        self.assertIsNone(event)
        self.assertEqual(error, ("forbidden", "not a member"))

        runtime.conversations.invite(conv_id, owner_user_id, [target_user_id])
        seq, event, error = _process_conv_send(
            runtime,
            target_session,
            {
                "conv_id": conv_id,
                "msg_id": "reinvited-send",
                "env": "ZW4=",
                "ts": message_count + 2,
            },
        )
        self.assertIsNone(error)
        self.assertIsNotNone(event)
        self.assertEqual(seq, last_seq + 1)
        last_seq = seq or last_seq

        for device_id, tracker in trackers.items():
            self.assertEqual(
                tracker.last_seq,
                last_seq,
                msg=f"device {device_id} did not reach last seq",
            )
            self.assertEqual(runtime.cursors.next_seq(device_id, conv_id), last_seq + 1)
            self.assertEqual(
                len(tracker.seen),
                last_seq,
                msg=f"device {device_id} missed events",
            )


if __name__ == "__main__":
    unittest.main()
