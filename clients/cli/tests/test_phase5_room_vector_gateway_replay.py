import asyncio
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional
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


def _load_vector(filename: str) -> dict:
    vector_path = ROOT_DIR / "clients" / "web" / "vectors" / filename
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


def _sse_first_event(
    base_url: str,
    session_token: str,
    *,
    conv_id: str,
    from_seq: Optional[int] = None,
    after_seq: Optional[int] = None,
    timeout_s: float,
) -> dict:
    query: dict[str, int | str] = {"conv_id": conv_id}
    if from_seq is not None:
        query["from_seq"] = from_seq
    if after_seq is not None:
        query["after_seq"] = after_seq
    url = f"{base_url.rstrip('/')}/v1/sse?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {session_token}"})
    data_lines: list[str] = []

    def _flush() -> dict | None:
        nonlocal data_lines
        if not data_lines:
            return None
        payload = "\n".join(data_lines)
        data_lines = []
        if not payload:
            return None
        try:
            parsed = json.loads(payload)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith(":"):
                    continue
                if not line:
                    event = _flush()
                    if event is not None:
                        return event
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:") :].lstrip())
    except socket.timeout as exc:
        raise AssertionError("Timed out waiting for SSE event") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            raise AssertionError("Timed out waiting for SSE event") from exc
        raise

    raise AssertionError("No SSE event received")


def _canonical_digest_for_vector(vector: dict, events: list[dict]) -> str:
    canonical = canonicalize_transcript(
        vector["conv_id"],
        vector["from_seq"],
        vector["next_seq"],
        events,
    )
    return compute_digest_sha256_b64(canonical)


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


async def _ws_open_session(client: TestClient, device_id: str):
    ws = await client.ws_connect("/v1/ws")
    await ws.send_json(
        {
            "v": 1,
            "t": "session.start",
            "id": f"start_{device_id}",
            "body": {"auth_token": "t", "device_id": device_id},
        }
    )
    await _ws_recv_until(
        ws,
        timeout_s=1.0,
        predicate=lambda payload: payload.get("t") == "session.ready",
    )
    return ws


async def _ws_first_event_after_seq(
    client: TestClient,
    *,
    conv_id: str,
    after_seq: int,
    device_id: str,
) -> dict:
    ws = await _ws_open_session(client, device_id)
    await ws.send_json(
        {
            "v": 1,
            "t": "conv.subscribe",
            "id": f"sub_after_{device_id}",
            "body": {"conv_id": conv_id, "after_seq": after_seq},
        }
    )
    payload = await _ws_recv_until(
        ws,
        timeout_s=1.0,
        predicate=lambda message: message.get("t") == "conv.event"
        and isinstance(message.get("body"), dict)
        and message["body"].get("conv_id") == conv_id,
    )
    await ws.close()
    return payload


async def _seed_events_via_inbox(
    base_url: str,
    session_token: str,
    *,
    vector: dict,
) -> None:
    for event in vector["events"]:
        response = await asyncio.to_thread(
            gateway_client.inbox_send,
            base_url,
            session_token,
            vector["conv_id"],
            event["msg_id"],
            event["env"],
        )
        if response["seq"] != event["seq"]:
            raise AssertionError(
                f"Unexpected seq {response['seq']} for msg {event['msg_id']}; expected {event['seq']}"
            )


async def _assert_legacy_after_seq_sse(
    base_url: str,
    session_token: str,
    *,
    conv_id: str,
    after_seq: int,
    expected_seq: int,
) -> None:
    payload = await asyncio.to_thread(
        _sse_first_event,
        base_url,
        session_token,
        conv_id=conv_id,
        after_seq=after_seq,
        timeout_s=2.0,
    )
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        raise AssertionError(f"Unexpected SSE payload: {payload}")
    seq = body.get("seq")
    if seq != expected_seq:
        raise AssertionError(f"Expected seq {expected_seq}, got {seq}")


class _Phase5GatewayReplayBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
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


class Phase5RoomVectorGatewayReplayTests(_Phase5GatewayReplayBase):
    async def test_room_vector_replay_via_gateway_sse(self) -> None:
        vector = _load_vector("room_seeded_bootstrap_v1.json")
        conv_id = vector["conv_id"]
        events = vector["events"]

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
        await _seed_events_via_inbox(
            self.base_url,
            session_token,
            vector=vector,
        )

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
        no_new_events = await asyncio.to_thread(
            _collect_sse_events,
            self.base_url,
            session_token,
            conv_id,
            vector["next_seq"],
            1,
            0.2,
        )
        self.assertEqual(no_new_events, [])

        captured = await asyncio.to_thread(
            capture_sse_transcript,
            self.base_url,
            session_token,
            conv_id,
            from_seq=vector["from_seq"],
            timeout_s=1.0,
            max_events=len(events),
        )
        events_by_seq = {event["seq"]: event for event in captured}
        if len(events_by_seq) < len(events):
            next_from_seq = max(events_by_seq) + 1 if events_by_seq else vector["from_seq"]
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

        digest_b64 = _canonical_digest_for_vector(vector, list(events_by_seq.values()))
        self.assertEqual(digest_b64, vector["digest_sha256_b64"])

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
        await _assert_legacy_after_seq_sse(
            self.base_url,
            session_token,
            conv_id=conv_id,
            after_seq=events[1]["seq"],
            expected_seq=events[1]["seq"] + 1,
        )

    async def test_room_vector_replay_via_gateway_ws(self) -> None:
        vector = _load_vector("room_seeded_bootstrap_v1.json")
        conv_id = vector["conv_id"]
        events = vector["events"]

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
        digest_b64 = _canonical_digest_for_vector(vector, replayed)
        self.assertEqual(digest_b64, vector["digest_sha256_b64"])

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

        legacy_payload = await _ws_first_event_after_seq(
            self.client,
            conv_id=conv_id,
            after_seq=events[1]["seq"],
            device_id="d4",
        )
        self.assertEqual(legacy_payload["body"]["seq"], events[1]["seq"] + 1)

        await ws.close()
        await ws_replay.close()
        await ws_middle.close()


class Phase5DmVectorGatewayReplayTests(_Phase5GatewayReplayBase):
    async def test_dm_vector_replay_via_gateway_sse(self) -> None:
        vector = _load_vector("interop_transcript_seeded_smoke_v2.json")
        conv_id = vector["conv_id"]
        events = vector["events"]

        session = await asyncio.to_thread(
            gateway_client.session_start,
            self.base_url,
            "t",
            "dm_d1",
        )
        session_token = session["session_token"]

        await asyncio.to_thread(
            gateway_client.room_create,
            self.base_url,
            session_token,
            conv_id,
            [],
        )

        await _seed_events_via_inbox(
            self.base_url,
            session_token,
            vector=vector,
        )

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
        no_new_events = await asyncio.to_thread(
            _collect_sse_events,
            self.base_url,
            session_token,
            conv_id,
            vector["next_seq"],
            1,
            0.2,
        )
        self.assertEqual(no_new_events, [])

        captured = await asyncio.to_thread(
            capture_sse_transcript,
            self.base_url,
            session_token,
            conv_id,
            from_seq=vector["from_seq"],
            timeout_s=1.0,
            max_events=len(events),
        )
        events_by_seq = {event["seq"]: event for event in captured}
        if len(events_by_seq) < len(events):
            next_from_seq = max(events_by_seq) + 1 if events_by_seq else vector["from_seq"]
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

        digest_b64 = _canonical_digest_for_vector(vector, list(events_by_seq.values()))
        self.assertEqual(digest_b64, vector["digest_sha256_b64"])

        await _assert_legacy_after_seq_sse(
            self.base_url,
            session_token,
            conv_id=conv_id,
            after_seq=events[0]["seq"],
            expected_seq=events[0]["seq"] + 1,
        )

    async def test_dm_vector_replay_via_gateway_ws(self) -> None:
        vector = _load_vector("interop_transcript_seeded_smoke_v2.json")
        conv_id = vector["conv_id"]
        events = vector["events"]

        session = await asyncio.to_thread(
            gateway_client.session_start,
            self.base_url,
            "t",
            "dm_seed",
        )
        session_token = session["session_token"]

        await asyncio.to_thread(
            gateway_client.room_create,
            self.base_url,
            session_token,
            conv_id,
            [],
        )

        await _seed_events_via_inbox(
            self.base_url,
            session_token,
            vector=vector,
        )

        ws = await _ws_open_session(self.client, "dm_ws1")
        await ws.send_json(
            {
                "v": 1,
                "t": "conv.subscribe",
                "id": "sub_dm_1",
                "body": {"conv_id": conv_id, "from_seq": vector["from_seq"]},
            }
        )
        replayed = await _ws_collect_events(
            ws,
            conv_id=conv_id,
            expected_count=len(events),
            timeout_s=1.0,
        )
        self.assertEqual(len(replayed), len(events))
        digest_b64 = _canonical_digest_for_vector(vector, replayed)
        self.assertEqual(digest_b64, vector["digest_sha256_b64"])

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
        await _ws_assert_no_app_messages(ws, timeout_s=0.2)

        legacy_payload = await _ws_first_event_after_seq(
            self.client,
            conv_id=conv_id,
            after_seq=events[0]["seq"],
            device_id="dm_ws2",
        )
        self.assertEqual(legacy_payload["body"]["seq"], events[0]["seq"] + 1)

        await ws.close()
