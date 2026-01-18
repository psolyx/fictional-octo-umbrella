import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY_SRC = ROOT_DIR / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from cli_app import gateway_client
from cli_app.interop_transcript import (
    canonicalize_transcript,
    capture_sse_transcript,
    compute_digest_sha256_b64,
)
from gateway.ws_transport import create_app


def _load_room_vector() -> dict:
    vector_path = (
        ROOT_DIR / "clients" / "web" / "vectors" / "room_seeded_bootstrap_v1.json"
    )
    with vector_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _collect_sse_events(
    base_url: str,
    session_token: str,
    conv_id: str,
    from_seq: int,
    max_events: int,
    idle_timeout_s: float,
) -> list[dict]:
    events: list[dict] = []
    for frame in gateway_client.sse_tail(
        base_url,
        session_token,
        conv_id,
        from_seq,
        max_events=max_events,
        idle_timeout_s=idle_timeout_s,
    ):
        if not isinstance(frame, dict) or frame.get("t") != "conv.event":
            continue
        body = frame.get("body")
        if not isinstance(body, dict):
            continue
        seq = body.get("seq")
        env = body.get("env")
        msg_id = body.get("msg_id") if isinstance(body.get("msg_id"), str) else None
        if not isinstance(seq, int) or not isinstance(env, str):
            continue
        events.append({"seq": seq, "msg_id": msg_id, "env": env})
        if len(events) >= max_events:
            break
    return events


async def _ws_receive_payload(
    ws,
    *,
    deadline: float,
) -> dict:
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError("Timed out waiting for websocket message")
        msg = await ws.receive(timeout=remaining)
        if msg.type == WSMsgType.PING:
            await ws.pong()
            continue
        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
            raise AssertionError("WebSocket closed while waiting for message")
        if msg.type == WSMsgType.ERROR:
            raise AssertionError(f"WebSocket error while waiting for message: {ws.exception()}")
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            payload = json.loads(msg.data)
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("t") == "ping":
            await ws.send_json({"v": 1, "t": "pong", "id": payload.get("id")})
            continue
        if isinstance(payload, dict):
            return payload


async def _ws_recv_until(
    ws,
    *,
    timeout_s: float,
    predicate,
    on_payload=None,
):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        payload = await _ws_receive_payload(ws, deadline=deadline)
        if on_payload is not None:
            on_payload(payload)
        if predicate(payload):
            return payload


def _record_ws_event(payload: dict, conv_id: str, events_by_seq: dict[int, dict]) -> bool:
    if payload.get("t") != "conv.event":
        return False
    body = payload.get("body")
    if not isinstance(body, dict):
        return False
    if body.get("conv_id") != conv_id:
        return False
    seq = body.get("seq")
    env = body.get("env")
    msg_id = body.get("msg_id") if isinstance(body.get("msg_id"), str) else None
    if not isinstance(seq, int) or not isinstance(env, str):
        return False
    events_by_seq.setdefault(seq, {"seq": seq, "msg_id": msg_id, "env": env})
    return True


async def _ws_collect_events(
    ws,
    *,
    conv_id: str,
    expected_count: int,
    timeout_s: float,
) -> list[dict]:
    events_by_seq: dict[int, dict] = {}
    deadline = asyncio.get_running_loop().time() + timeout_s
    while len(events_by_seq) < expected_count:
        try:
            payload = await _ws_receive_payload(ws, deadline=deadline)
        except asyncio.TimeoutError:
            break
        _record_ws_event(payload, conv_id, events_by_seq)
    return list(events_by_seq.values())


async def _ws_assert_no_app_messages(ws, *, timeout_s: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        try:
            payload = await _ws_receive_payload(ws, deadline=deadline)
        except asyncio.TimeoutError:
            return
        raise AssertionError(f"Unexpected websocket message: {payload}")


class Phase5RoomVectorGatewayReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.vector = _load_room_vector()
        db_file = tempfile.NamedTemporaryFile(delete=False)
        db_file.close()
        self.app = create_app(db_path=db_file.name)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.base_url = str(self.server.make_url(""))

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()

    async def test_room_vector_replay_via_gateway_sse(self) -> None:
        conv_id = self.vector["conv_id"]
        events = self.vector["events"]

        session = await asyncio.to_thread(
            gateway_client.session_start,
            self.base_url,
            "t",
            "d1",
        )
        session_token = session["session_token"]
        await asyncio.to_thread(
            gateway_client.room_create,
            self.base_url,
            session_token,
            conv_id,
            [],
        )

        for event in events:
            response = await asyncio.to_thread(
                gateway_client.inbox_send,
                self.base_url,
                session_token,
                conv_id,
                event["msg_id"],
                event["env"],
            )
            self.assertEqual(response["seq"], event["seq"])

        resend_event = events[1]
        resend_response = await asyncio.to_thread(
            gateway_client.inbox_send,
            self.base_url,
            session_token,
            conv_id,
            resend_event["msg_id"],
            resend_event["env"],
        )
        self.assertEqual(resend_response["seq"], resend_event["seq"])

        captured = await asyncio.to_thread(
            capture_sse_transcript,
            self.base_url,
            session_token,
            conv_id,
            from_seq=1,
            timeout_s=1.0,
            max_events=len(events),
        )
        events_by_seq = {event["seq"]: event for event in captured}
        if len(events_by_seq) < len(events):
            next_from_seq = max(events_by_seq) + 1 if events_by_seq else 1
            remaining = await asyncio.to_thread(
                _collect_sse_events,
                self.base_url,
                session_token,
                conv_id,
                next_from_seq,
                len(events) - len(events_by_seq),
                1.0,
            )
            for event in remaining:
                events_by_seq.setdefault(event["seq"], event)

        self.assertEqual(len(events_by_seq), len(events))

        canonical = canonicalize_transcript(
            conv_id,
            1,
            self.vector["next_seq"],
            list(events_by_seq.values()),
        )
        digest_b64 = compute_digest_sha256_b64(canonical)
        self.assertEqual(digest_b64, self.vector["digest_sha256_b64"])

        middle_seq = events[2]["seq"]
        replayed = await asyncio.to_thread(
            capture_sse_transcript,
            self.base_url,
            session_token,
            conv_id,
            from_seq=middle_seq,
            timeout_s=1.0,
            max_events=len(events),
        )
        self.assertGreaterEqual(len(replayed), 1)
        self.assertEqual(replayed[0]["seq"], middle_seq)
        self.assertTrue(all(event["seq"] >= middle_seq for event in replayed))

    async def test_room_vector_replay_via_gateway_ws(self) -> None:
        conv_id = self.vector["conv_id"]
        events = self.vector["events"]

        ws = await self.client.ws_connect("/v1/ws")
        await ws.send_json(
            {
                "v": 1,
                "t": "session.start",
                "id": "start1",
                "body": {"auth_token": "t", "device_id": "d1"},
            }
        )
        ready = await _ws_recv_until(
            ws,
            timeout_s=1.0,
            predicate=lambda payload: payload.get("t") == "session.ready",
        )
        session_token = ready["body"]["session_token"]

        resp = await self.client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

        await ws.send_json(
            {
                "v": 1,
                "t": "conv.subscribe",
                "id": "sub1",
                "body": {"conv_id": conv_id, "from_seq": 1},
            }
        )

        events_by_seq: dict[int, dict] = {}
        for idx, event in enumerate(events):
            send_id = f"send{idx}"
            await ws.send_json(
                {
                    "v": 1,
                    "t": "conv.send",
                    "id": send_id,
                    "body": {
                        "conv_id": conv_id,
                        "msg_id": event["msg_id"],
                        "env": event["env"],
                    },
                }
            )
            ack = await _ws_recv_until(
                ws,
                timeout_s=1.0,
                predicate=lambda payload, expected_id=send_id: (
                    payload.get("t") == "conv.acked" and payload.get("id") == expected_id
                ),
                on_payload=lambda payload: _record_ws_event(payload, conv_id, events_by_seq),
            )
            self.assertEqual(ack["body"]["seq"], event["seq"])

        if len(events_by_seq) < len(events):
            remaining = await _ws_collect_events(
                ws,
                conv_id=conv_id,
                expected_count=len(events),
                timeout_s=1.0,
            )
            for event in remaining:
                events_by_seq.setdefault(event["seq"], event)

        self.assertEqual(len(events_by_seq), len(events))

        resend_event = events[1]
        await ws.send_json(
            {
                "v": 1,
                "t": "conv.send",
                "id": "resend1",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": resend_event["msg_id"],
                    "env": resend_event["env"],
                },
            }
        )
        resend_ack = await _ws_recv_until(
            ws,
            timeout_s=1.0,
            predicate=lambda payload: payload.get("t") == "conv.acked"
            and payload.get("id") == "resend1",
            on_payload=lambda payload: _record_ws_event(payload, conv_id, events_by_seq),
        )
        self.assertEqual(resend_ack["body"]["seq"], resend_event["seq"])
        await _ws_assert_no_app_messages(ws, timeout_s=0.2)

        ws_replay = await self.client.ws_connect("/v1/ws")
        await ws_replay.send_json(
            {
                "v": 1,
                "t": "session.start",
                "id": "start2",
                "body": {"auth_token": "t", "device_id": "d2"},
            }
        )
        await _ws_recv_until(
            ws_replay,
            timeout_s=1.0,
            predicate=lambda payload: payload.get("t") == "session.ready",
        )
        await ws_replay.send_json(
            {
                "v": 1,
                "t": "conv.subscribe",
                "id": "sub2",
                "body": {"conv_id": conv_id, "from_seq": 1},
            }
        )
        replayed = await _ws_collect_events(
            ws_replay,
            conv_id=conv_id,
            expected_count=len(events),
            timeout_s=1.0,
        )
        self.assertEqual(len(replayed), len(events))
        canonical = canonicalize_transcript(
            conv_id,
            1,
            self.vector["next_seq"],
            replayed,
        )
        digest_b64 = compute_digest_sha256_b64(canonical)
        self.assertEqual(digest_b64, self.vector["digest_sha256_b64"])

        middle_seq = events[2]["seq"]
        middle_index = next(
            index for index, event in enumerate(events) if event["seq"] == middle_seq
        )
        expected_remaining = len(events) - middle_index
        ws_middle = await self.client.ws_connect("/v1/ws")
        await ws_middle.send_json(
            {
                "v": 1,
                "t": "session.start",
                "id": "start3",
                "body": {"auth_token": "t", "device_id": "d3"},
            }
        )
        await _ws_recv_until(
            ws_middle,
            timeout_s=1.0,
            predicate=lambda payload: payload.get("t") == "session.ready",
        )
        await ws_middle.send_json(
            {
                "v": 1,
                "t": "conv.subscribe",
                "id": "sub3",
                "body": {"conv_id": conv_id, "from_seq": middle_seq},
            }
        )
        middle_replay = await _ws_collect_events(
            ws_middle,
            conv_id=conv_id,
            expected_count=expected_remaining,
            timeout_s=1.0,
        )
        self.assertGreaterEqual(len(middle_replay), 1)
        middle_replay.sort(key=lambda entry: entry["seq"])
        self.assertEqual(middle_replay[0]["seq"], middle_seq)
        self.assertTrue(all(event["seq"] >= middle_seq for event in middle_replay))

        await ws.close()
        await ws_replay.close()
        await ws_middle.close()
