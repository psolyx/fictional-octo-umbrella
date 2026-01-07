import asyncio
import importlib
import importlib.metadata
import json
import os
import unittest

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway WS tests")

from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway WS tests, found {_installed_aiohttp}"
    )

from gateway.ws_transport import SessionStore, _process_conv_send, create_app


class ResumeTokenRotationTests(unittest.TestCase):
    def test_resume_token_rotates_over_many_cycles(self):
        sessions = SessionStore()
        session = sessions.create("user", "device")

        session_token = session.session_token
        resume_token = session.resume_token

        seen_tokens = {resume_token}

        iterations = 500

        for _ in range(iterations):
            resumed = sessions.consume_resume(resume_token)
            self.assertIsNotNone(resumed)
            self.assertEqual(resumed.session_token, session_token)

            resume_token = resumed.resume_token
            self.assertNotIn(resume_token, seen_tokens)
            seen_tokens.add(resume_token)

            active = sessions.get_by_session(session_token)
            self.assertIs(active, resumed)

        self.assertEqual(len(seen_tokens), iterations + 1)


class ResumeChaosTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(ping_interval_s=3600)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def _post_json(self, path: str, payload: dict, *, headers: dict | None = None):
        resp = await asyncio.wait_for(
            self.client.post(path, json=payload, headers=headers), timeout=3.0
        )
        return resp

    async def _fetch_json(self, resp):
        return await asyncio.wait_for(resp.json(), timeout=3.0)

    async def test_resume_chaos_no_loss_or_duplication(self):
        conv_id = "chaos-room"
        run_slow = os.getenv("RUN_SLOW_TESTS") == "1"

        iterations = 2_000 if run_slow else 60
        send_interval = 100 if run_slow else 10
        ack_every = 10 if run_slow else 2
        test_timeout = 90 if run_slow else 15
        sse_timeout = 30 if run_slow else 6

        async with asyncio.timeout(test_timeout):
            start_resp = await self._post_json(
                "/v1/session/start", {"auth_token": "user", "device_id": "device"}
            )
            self.assertEqual(start_resp.status, 200)
            ready = await self._fetch_json(start_resp)
            session_token = ready["session_token"]
            resume_token = ready["resume_token"]

            create_resp = await self._post_json(
                "/v1/rooms/create",
                {"conv_id": conv_id, "members": []},
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(create_resp.status, 200)
            await self._fetch_json(create_resp)

            sent_messages: list[tuple[str, int]] = []
            last_seq = 0

            for i in range(iterations):
                resume_resp = await self._post_json(
                    "/v1/session/resume", {"resume_token": resume_token}
                )
                self.assertEqual(resume_resp.status, 200)
                ready = await self._fetch_json(resume_resp)
                session_token = ready["session_token"]
                new_resume_token = ready["resume_token"]
                self.assertNotEqual(new_resume_token, resume_token)
                resume_token = new_resume_token

                if (i + 1) % send_interval == 0:
                    msg_id = f"m{len(sent_messages) + 1}"
                    send_resp = await self._post_json(
                        "/v1/inbox",
                        {
                            "v": 1,
                            "t": "conv.send",
                            "body": {"conv_id": conv_id, "msg_id": msg_id, "env": "ZW4=", "ts": i},
                        },
                        headers={"Authorization": f"Bearer {session_token}"},
                    )
                    self.assertEqual(send_resp.status, 200)
                    send_body = await self._fetch_json(send_resp)
                    last_seq = send_body["seq"]
                    sent_messages.append((msg_id, last_seq))

                    if len(sent_messages) % ack_every == 0:
                        ack_resp = await self._post_json(
                            "/v1/inbox",
                            {
                                "v": 1,
                                "t": "conv.ack",
                                "body": {"conv_id": conv_id, "seq": last_seq},
                            },
                            headers={"Authorization": f"Bearer {session_token}"},
                        )
                        self.assertEqual(ack_resp.status, 200)
                        await self._fetch_json(ack_resp)

        expected_events = len(sent_messages)
        self.assertGreater(expected_events, 0)

        events: list[dict] = []
        headers = {"Authorization": f"Bearer {session_token}"}
        async with asyncio.timeout(sse_timeout):
            async with self.client.get(
                f"/v1/sse?conv_id={conv_id}&from_seq=1", headers=headers
            ) as sse_resp:
                self.assertEqual(sse_resp.status, 200)
                while len(events) < expected_events:
                    line = await asyncio.wait_for(sse_resp.content.readline(), timeout=2.0)
                    if not line:
                        continue
                    if line.startswith(b"data: "):
                        payload = json.loads(line[len(b"data: ") :].decode("utf-8"))
                        events.append(payload)

        self.assertEqual(len(events), expected_events)
        msg_ids = [event["body"]["msg_id"] for event in events]
        seqs = [event["body"]["seq"] for event in events]

        self.assertEqual(msg_ids, [msg for msg, _ in sent_messages])
        self.assertEqual(seqs, list(range(1, expected_events + 1)))
        self.assertEqual(len(set(msg_ids)), expected_events)


class ResumeStormInvariantTests(unittest.TestCase):
    def test_resume_storm_preserves_order_and_idempotency(self):
        app = create_app(ping_interval_s=3600, start_presence_sweeper=False)
        runtime = app["runtime"]

        user_id = "user"
        device_id = "device"
        conv_id = "resume-storm"

        runtime.conversations.create(conv_id, user_id, members=[], home_gateway=runtime.gateway_id)
        session = runtime.sessions.create(user_id, device_id)
        resume_token = session.resume_token

        events: list = []

        def on_event(event):
            events.append(event)

        subscription = runtime.hub.subscribe(device_id, conv_id, on_event)

        send_every = 40
        expected_next_seq = 1
        last_seq = 0
        msg_count = 0

        try:
            for i in range(500):
                resumed = runtime.sessions.consume_resume(resume_token)
                self.assertIsNotNone(resumed)
                session = resumed
                resume_token = resumed.resume_token

                if (i + 1) % send_every == 0:
                    msg_count += 1
                    msg_id = f"m{msg_count}"
                    body = {"conv_id": conv_id, "msg_id": msg_id, "env": "ZW4=", "ts": i}

                    seq, event, error = _process_conv_send(runtime, session, body)
                    self.assertIsNone(error)
                    self.assertIsNotNone(seq)
                    self.assertIsNotNone(event)
                    self.assertEqual(len(events), msg_count)
                    self.assertGreater(seq, last_seq)

                    seq_retry, event_retry, retry_error = _process_conv_send(runtime, session, body)
                    self.assertIsNone(retry_error)
                    self.assertEqual(seq_retry, seq)
                    self.assertIs(event_retry, event)
                    self.assertEqual(len(events), msg_count)

                    last_seq = seq
                    next_seq = runtime.cursors.ack(session.device_id, conv_id, seq)
                    expected_next_seq = max(expected_next_seq, seq + 1)
                    self.assertEqual(next_seq, expected_next_seq)
                    self.assertEqual(runtime.cursors.next_seq(session.device_id, conv_id), expected_next_seq)
        finally:
            runtime.hub.unsubscribe(subscription)

        self.assertEqual(msg_count, len(events))
        seqs = [event.seq for event in events]
        msg_ids = [event.msg_id for event in events]
        self.assertEqual(seqs, list(range(1, msg_count + 1)))
        self.assertEqual(msg_ids, [f"m{i}" for i in range(1, msg_count + 1)])
        self.assertEqual(runtime.cursors.next_seq(device_id, conv_id), last_seq + 1)


if __name__ == "__main__":
    unittest.main()
