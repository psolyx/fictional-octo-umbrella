import asyncio
import importlib
import importlib.metadata
import json
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

from gateway.ws_transport import create_app


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
            self.client.post(path, json=payload, headers=headers), timeout=1.0
        )
        return resp

    async def _fetch_json(self, resp):
        return await asyncio.wait_for(resp.json(), timeout=1.0)

    async def test_resume_chaos_no_loss_or_duplication(self):
        conv_id = "chaos-room"
        iterations = 10_000
        send_interval = 10
        ack_every = 100

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
            resume_token = ready["resume_token"]

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
        async with asyncio.timeout(5):
            async with self.client.get(
                f"/v1/sse?conv_id={conv_id}&from_seq=1", headers=headers
            ) as sse_resp:
                self.assertEqual(sse_resp.status, 200)
                while len(events) < expected_events:
                    line = await asyncio.wait_for(sse_resp.content.readline(), timeout=1.0)
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


if __name__ == "__main__":
    unittest.main()
