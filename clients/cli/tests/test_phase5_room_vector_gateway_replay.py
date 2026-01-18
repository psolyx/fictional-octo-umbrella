import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

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
