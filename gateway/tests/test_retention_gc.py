import importlib
import os
import tempfile
import unittest
from unittest import mock

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway retention tests")

from aiohttp.test_utils import TestClient, TestServer

from gateway.sqlite_cursors import SQLiteCursorStore
from gateway.sqlite_log import SQLiteConversationLog
from gateway.ws_transport import RUNTIME_KEY, create_app


class RetentionGCTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "gateway.db")
        self._servers: list[tuple[TestServer, TestClient]] = []

    async def asyncTearDown(self) -> None:
        for server, client in self._servers:
            await client.close()
            await server.close()
        self.tmpdir.cleanup()

    async def _start_runtime(self) -> TestClient:
        app = create_app(ping_interval_s=3600, db_path=self.db_path)
        server = TestServer(app)
        await server.start_server()
        client = TestClient(server)
        await client.start_server()
        self._servers.append((server, client))
        return client

    async def _start_session_http(self, client: TestClient, *, auth_token: str = "u1", device_id: str = "d1") -> dict:
        resp = await client.post("/v1/session/start", json={"auth_token": auth_token, "device_id": device_id})
        self.assertEqual(resp.status, 200)
        return await resp.json()

    async def _create_room(self, client: TestClient, session_token: str, conv_id: str) -> None:
        resp = await client.post(
            "/v1/rooms/create",
            json={"conv_id": conv_id, "members": []},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        await resp.json()

    async def _send_inbox(self, client: TestClient, session_token: str, frame: dict) -> dict:
        resp = await client.post(
            "/v1/inbox",
            json=frame,
            headers={"Authorization": f"Bearer {session_token}"},
        )
        self.assertEqual(resp.status, 200)
        return await resp.json()

    async def test_hard_limit_prunes_and_sse_returns_410_for_pruned_from_seq(self) -> None:
        env = {
            "GATEWAY_RETENTION_MAX_EVENTS_PER_CONV": "5",
            "GATEWAY_RETENTION_MAX_AGE_S": "0",
            "GATEWAY_RETENTION_HARD_LIMITS": "1",
            "GATEWAY_RETENTION_SWEEP_INTERVAL_S": "60",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            client = await self._start_runtime()
            ready = await self._start_session_http(client)
            session_token = ready["session_token"]
            await self._create_room(client, session_token, "c1")

            for idx in range(10):
                await self._send_inbox(
                    client,
                    session_token,
                    {
                        "v": 1,
                        "t": "conv.send",
                        "body": {"conv_id": "c1", "msg_id": f"m{idx}", "env": "ZW4=", "ts": idx + 1},
                    },
                )

            runtime = self._servers[-1][0].app[RUNTIME_KEY]
            assert isinstance(runtime.log, SQLiteConversationLog)
            earliest_seq = runtime.log.earliest_seq("c1")
            self.assertIsNotNone(earliest_seq)
            self.assertGreater(earliest_seq, 1)

            ws = await client.ws_connect("/v1/ws")
            await ws.send_json(
                {
                    "v": 1,
                    "t": "session.start",
                    "id": "start_ws",
                    "body": {"auth_token": "u1", "device_id": "d_ws"},
                }
            )
            await ws.receive_json()
            await ws.send_json(
                {
                    "v": 1,
                    "t": "conv.subscribe",
                    "id": "sub_old",
                    "body": {"conv_id": "c1", "from_seq": 1},
                }
            )
            ws_error = await ws.receive_json()
            self.assertEqual(ws_error["t"], "error")
            self.assertEqual(ws_error["body"]["code"], "replay_window_exceeded")
            self.assertEqual(ws_error["body"]["requested_from_seq"], 1)
            self.assertEqual(ws_error["body"]["earliest_seq"], earliest_seq)
            self.assertGreaterEqual(ws_error["body"]["latest_seq"], earliest_seq)
            await ws.close()

            replay_resp = await client.get(
                "/v1/sse",
                params={"conv_id": "c1", "from_seq": "1"},
                headers={"Authorization": f"Bearer {session_token}"},
            )
            self.assertEqual(replay_resp.status, 410)
            body = await replay_resp.json()
            self.assertEqual(body["code"], "replay_window_exceeded")
            self.assertEqual(body["earliest_seq"], earliest_seq)
            self.assertGreaterEqual(body["latest_seq"], earliest_seq)


    async def test_ws_replay_window_error_includes_structured_fields(self) -> None:
        env = {
            "GATEWAY_RETENTION_MAX_EVENTS_PER_CONV": "2",
            "GATEWAY_RETENTION_MAX_AGE_S": "0",
            "GATEWAY_RETENTION_HARD_LIMITS": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            client = await self._start_runtime()
            ready = await self._start_session_http(client, device_id="d1")
            session_token = ready["session_token"]
            await self._create_room(client, session_token, "c1")

            for idx in range(4):
                await self._send_inbox(
                    client,
                    session_token,
                    {
                        "v": 1,
                        "t": "conv.send",
                        "body": {"conv_id": "c1", "msg_id": f"m{idx}", "env": "ZW4=", "ts": idx + 1},
                    },
                )

            runtime = self._servers[-1][0].app[RUNTIME_KEY]
            assert isinstance(runtime.log, SQLiteConversationLog)
            earliest_seq = runtime.log.earliest_seq("c1")
            latest_seq = runtime.log.latest_seq("c1")
            self.assertIsNotNone(earliest_seq)
            self.assertIsNotNone(latest_seq)

            ws = await client.ws_connect("/v1/ws")
            await ws.send_json(
                {
                    "v": 1,
                    "t": "session.start",
                    "id": "start_ws",
                    "body": {"auth_token": "u1", "device_id": "d_ws"},
                }
            )
            await ws.receive_json()
            await ws.send_json(
                {
                    "v": 1,
                    "t": "conv.subscribe",
                    "id": "sub_old",
                    "body": {"conv_id": "c1", "from_seq": 1},
                }
            )
            ws_error = await ws.receive_json()
            self.assertEqual(ws_error["t"], "error")
            self.assertEqual(ws_error["body"]["code"], "replay_window_exceeded")
            self.assertEqual(ws_error["body"]["requested_from_seq"], 1)
            self.assertEqual(ws_error["body"]["earliest_seq"], earliest_seq)
            self.assertEqual(ws_error["body"]["latest_seq"], latest_seq)
            self.assertIn("requested_from_seq=1", ws_error["body"]["message"])
            await ws.close()

    async def test_safe_mode_preserves_unacked_history_for_active_cursors(self) -> None:
        env = {
            "GATEWAY_RETENTION_MAX_EVENTS_PER_CONV": "3",
            "GATEWAY_RETENTION_MAX_AGE_S": "0",
            "GATEWAY_RETENTION_HARD_LIMITS": "0",
            "GATEWAY_CURSOR_STALE_AFTER_S": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            client = await self._start_runtime()
            runtime = self._servers[-1][0].app[RUNTIME_KEY]
            assert isinstance(runtime.log, SQLiteConversationLog)
            assert isinstance(runtime.cursors, SQLiteCursorStore)

            for seq in range(1, 9):
                runtime.log.append("c1", f"m{seq}", "ZW4=", "d_sender", ts_ms=seq)

            runtime.cursors.ack("d_active_fast", "c1", 7)
            runtime.cursors.ack("d_active_slow", "c1", 2)

            now_ms = runtime.now_func()
            active_min = runtime.cursors.active_min_next_seq(
                "c1", now_ms, runtime.retention_policy.cursor_stale_after_ms
            )
            deleted = runtime.log.prune_conv("c1", runtime.retention_policy, now_ms, active_min)

            self.assertGreater(deleted, 0)
            self.assertEqual(runtime.log.earliest_seq("c1"), 3)
            remaining = runtime.log.list_from("c1", 3)
            self.assertEqual([event.seq for event in remaining], [3, 4, 5, 6, 7, 8])

    async def test_max_age_prunes_old_rows(self) -> None:
        env = {
            "GATEWAY_RETENTION_MAX_EVENTS_PER_CONV": "0",
            "GATEWAY_RETENTION_MAX_AGE_S": "1",
            "GATEWAY_RETENTION_HARD_LIMITS": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            client = await self._start_runtime()
            runtime = self._servers[-1][0].app[RUNTIME_KEY]
            assert isinstance(runtime.log, SQLiteConversationLog)

            now_ms = runtime.now_func()
            runtime.log.append("c_age", "m_old", "ZW4=", "d1", ts_ms=now_ms - 5000)
            runtime.log.append("c_age", "m_new", "ZW4=", "d1", ts_ms=now_ms)

            deleted = runtime.log.prune_conv("c_age", runtime.retention_policy, now_ms, None)
            self.assertEqual(deleted, 1)
            remaining = runtime.log.list_from("c_age", 2)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].msg_id, "m_new")


if __name__ == "__main__":
    unittest.main()
