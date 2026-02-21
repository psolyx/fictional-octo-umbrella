import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY_SRC = ROOT_DIR / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from aiohttp.test_utils import TestClient, TestServer

from cli_app import gateway_client
from gateway.ws_transport import create_app


class ReplayWindowCliHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "gateway.db")
        self._servers: list[tuple[TestServer, TestClient]] = []

    async def asyncTearDown(self) -> None:
        for server, client in self._servers:
            await client.close()
            await server.close()
        self.tmpdir.cleanup()

    async def _start_runtime(self) -> tuple[TestClient, str]:
        app = create_app(ping_interval_s=3600, db_path=self.db_path)
        server = TestServer(app)
        await server.start_server()
        client = TestClient(server)
        await client.start_server()
        self._servers.append((server, client))
        return client, str(client.make_url("/")).rstrip("/")

    async def _session_token(self, client: TestClient, *, device_id: str = "d1") -> str:
        response = await client.post(
            "/v1/session/start",
            json={"auth_token": "u1", "device_id": device_id},
        )
        self.assertEqual(response.status, 200)
        body = await response.json()
        return body["session_token"]

    async def _create_room(self, client: TestClient, session_token: str, conv_id: str = "c1") -> None:
        response = await client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(response.status, 200)

    async def _append_events(self, client: TestClient, session_token: str, count: int, conv_id: str = "c1") -> None:
        for seq in range(1, count + 1):
            response = await client.post(
                "/v1/inbox",
                json={
                    "v": 1,
                    "t": "conv.send",
                    "body": {
                        "conv_id": conv_id,
                        "msg_id": f"m{seq}",
                        "env": "ZW52",
                        "ts": seq,
                    },
                },
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(response.status, 200)


    async def test_sse_tail_raises_typed_error_for_410_replay_window(self) -> None:
        env = {
            "GATEWAY_RETENTION_MAX_EVENTS_PER_CONV": "3",
            "GATEWAY_RETENTION_MAX_AGE_S": "0",
            "GATEWAY_RETENTION_HARD_LIMITS": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            client, base_url = await self._start_runtime()
            session_token = await self._session_token(client)
            await self._create_room(client, session_token)
            await self._append_events(client, session_token, count=8)

            def _run_tail() -> list[dict[str, object]]:
                return list(
                    gateway_client.sse_tail(
                        base_url,
                        session_token,
                        "c1",
                        from_seq=1,
                        max_events=1,
                        idle_timeout_s=0.5,
                    )
                )

            with self.assertRaises(gateway_client.ReplayWindowExceededError) as caught:
                await asyncio.to_thread(_run_tail)

            error = caught.exception
            self.assertGreaterEqual(error.earliest_seq, 2)
            self.assertGreaterEqual(error.latest_seq, error.earliest_seq)
            self.assertGreaterEqual(error.requested_from_seq, error.earliest_seq)

    async def test_sse_tail_resilient_recovers_using_earliest_seq(self) -> None:
        env = {
            "GATEWAY_RETENTION_MAX_EVENTS_PER_CONV": "4",
            "GATEWAY_RETENTION_MAX_AGE_S": "0",
            "GATEWAY_RETENTION_HARD_LIMITS": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            client, base_url = await self._start_runtime()
            session_token = await self._session_token(client)
            await self._create_room(client, session_token)
            await self._append_events(client, session_token, count=9)

            reset_errors: list[gateway_client.ReplayWindowExceededError] = []

            def _run_tail_resilient() -> list[dict[str, object]]:
                return list(
                    gateway_client.sse_tail_resilient(
                        base_url,
                        session_token,
                        "c1",
                        from_seq=1,
                        max_events=3,
                        idle_timeout_s=0.5,
                        on_reset_callback=reset_errors.append,
                        emit_reset_control_event=True,
                    )
                )

            events = await asyncio.to_thread(_run_tail_resilient)

            self.assertEqual(len(reset_errors), 1)
            self.assertGreaterEqual(reset_errors[0].earliest_seq, 2)
            control_event = events[0]
            self.assertEqual(control_event["t"], "control.replay_window_reset")
            data_events = [event for event in events if event.get("t") == "conv.event"]
            self.assertEqual(len(data_events), 3)
            first_seq = data_events[0]["body"]["seq"]
            self.assertEqual(first_seq, reset_errors[0].earliest_seq)


if __name__ == "__main__":
    unittest.main()
