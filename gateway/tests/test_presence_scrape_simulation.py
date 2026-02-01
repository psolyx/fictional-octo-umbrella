import asyncio
import importlib
import importlib.metadata
import unittest

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway presence tests")

from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway presence tests, found {_installed_aiohttp}"
    )

from gateway.presence import Presence, PresenceConfig
from gateway.ws_transport import RUNTIME_KEY, create_app
from ws_receive_util import assert_no_app_messages, recv_json_until


class FakeClock:
    def __init__(self, start_ms: int = 0) -> None:
        self.now_ms = start_ms

    def advance(self, seconds: float) -> None:
        self.now_ms += int(seconds * 1000)

    def now(self) -> int:
        return self.now_ms


class PresenceScrapeSimulationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        if hasattr(self, "client") and self.client:
            await self.client.close()
        if hasattr(self, "server") and self.server:
            await self.server.close()

    async def _setup_app(self, presence: Presence) -> None:
        self.app = create_app(ping_interval_s=3600, presence=presence, start_presence_sweeper=False)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def _start_ws(self, user_id: str, device_id: str):
        ws = await self.client.ws_connect("/v1/ws")
        await ws.send_json(
            {"v": 1, "t": "session.start", "id": "start", "body": {"auth_token": user_id, "device_id": device_id}}
        )
        await ws.receive_json()
        return ws

    async def _create_session(self, user_id: str, device_id: str):
        runtime = self.app[RUNTIME_KEY]
        return runtime.sessions.create(user_id, device_id)

    async def _post(self, path: str, *, session, json: dict) -> TestClient:
        return await self.client.post(path, json=json, headers={"Authorization": f"Bearer {session.session_token}"})

    async def _expect_error(self, response, *, status: int, code: str) -> None:
        self.assertEqual(response.status, status)
        payload = await response.json()
        self.assertEqual(payload["code"], code)

    async def _expect_status(self, response, *, status: int) -> dict:
        self.assertEqual(response.status, status)
        return await response.json()

    def _assert_watch_count(self, payload: dict, *, expected: int) -> None:
        self.assertEqual(payload.get("watching"), expected)

    def _assert_block_count(self, payload: dict, *, expected: int) -> None:
        self.assertEqual(payload.get("blocked"), expected)

    def _assert_presence_update_shape(self, update: dict) -> None:
        self.assertEqual(update.get("t"), "presence.update")
        body = update.get("body", {})
        self.assertIsInstance(body.get("user_id"), str)
        self.assertIn(body.get("status"), {"online", "offline"})
        self.assertIsInstance(body.get("expires_at"), int)
        self.assertIn("last_seen_bucket", body)
        self.assertIn(body.get("last_seen_bucket"), {"now", "5m", "1h", "1d", "7d"})
        self.assertNotIn("last_seen", body)
        self.assertNotIn("last_seen_ms", body)
        self.assertNotIn("last_seen_at", body)
        self.assertNotIn("last_seen_ts", body)
        self.assertNotIn("last_seen_timestamp", body)
        self.assertNotIn("timestamp", body)
        disallowed = [key for key in body if key.startswith("last_seen_") and key != "last_seen_bucket"]
        self.assertEqual(disallowed, [])

    async def _next_presence_update(self, ws) -> dict:
        deadline = asyncio.get_running_loop().time() + 1
        update = await recv_json_until(ws, deadline=deadline, predicate=lambda msg: msg.get("t") == "presence.update")
        self._assert_presence_update_shape(update)
        return update

    async def test_scrape_simulation_rr_002(self):
        clock = FakeClock()
        presence = Presence(
            PresenceConfig(
                max_watchlist_size=8,
                watch_mutations_per_min=5,
                max_watchers_per_target=4,
                block_mutations_per_min=10,
                renews_per_min=10,
                min_ttl_seconds=1,
            ),
            now_func=clock.now,
        )
        await self._setup_app(presence)

        bot = await self._create_session("bot-watcher", "bot-device")
        normal = await self._create_session("normal-watcher", "normal-device")
        targets = []
        for idx in range(10):
            targets.append(await self._create_session(f"target-{idx}", f"t-{idx}"))
        target_ids = [session.user_id for session in targets]

        bot_large_watch = await self._post(
            "/v1/presence/watch",
            session=bot,
            json={"contacts": target_ids[:9]},
        )
        await self._expect_error(bot_large_watch, status=429, code="limit_exceeded")

        bot_watch_1 = await self._post(
            "/v1/presence/watch",
            session=bot,
            json={"contacts": [target_ids[0]]},
        )
        bot_watch_1_body = await self._expect_status(bot_watch_1, status=200)
        self._assert_watch_count(bot_watch_1_body, expected=1)

        bot_watch_2 = await self._post(
            "/v1/presence/watch",
            session=bot,
            json={"contacts": [target_ids[1]]},
        )
        bot_watch_2_body = await self._expect_status(bot_watch_2, status=200)
        self._assert_watch_count(bot_watch_2_body, expected=2)

        bot_unwatch_1 = await self._post(
            "/v1/presence/unwatch",
            session=bot,
            json={"contacts": [target_ids[0]]},
        )
        bot_unwatch_1_body = await self._expect_status(bot_unwatch_1, status=200)
        self._assert_watch_count(bot_unwatch_1_body, expected=1)

        bot_unwatch_2 = await self._post(
            "/v1/presence/unwatch",
            session=bot,
            json={"contacts": [target_ids[1]]},
        )
        bot_unwatch_2_body = await self._expect_status(bot_unwatch_2, status=200)
        self._assert_watch_count(bot_unwatch_2_body, expected=0)

        bot_rate_limited = await self._post(
            "/v1/presence/watch",
            session=bot,
            json={"contacts": [target_ids[2]]},
        )
        await self._expect_error(bot_rate_limited, status=429, code="rate_limited")

        extra_watchers = []
        for idx in range(5):
            extra_watchers.append(await self._create_session(f"extra-watcher-{idx}", f"ew-{idx}"))

        for watcher in extra_watchers[:4]:
            watcher_watch = await self._post(
                "/v1/presence/watch",
                session=watcher,
                json={"contacts": [target_ids[2]]},
            )
            watcher_watch_body = await self._expect_status(watcher_watch, status=200)
            self._assert_watch_count(watcher_watch_body, expected=1)

        watcher_cap = await self._post(
            "/v1/presence/watch",
            session=extra_watchers[4],
            json={"contacts": [target_ids[2]]},
        )
        await self._expect_error(watcher_cap, status=429, code="limit_exceeded")

        normal_watch = await self._post(
            "/v1/presence/watch",
            session=normal,
            json={"contacts": [target_ids[0], target_ids[1]]},
        )
        normal_watch_body = await self._expect_status(normal_watch, status=200)
        self._assert_watch_count(normal_watch_body, expected=2)

        normal_ws = await self._start_ws("normal-watcher", "normal-device")

        target0_lease = await self._post(
            "/v1/presence/lease",
            session=targets[0],
            json={"device_id": "t-0", "ttl_seconds": 30},
        )
        await self._expect_status(target0_lease, status=200)
        await assert_no_app_messages(normal_ws, timeout=0.5)

        target0_watch = await self._post(
            "/v1/presence/watch",
            session=targets[0],
            json={"contacts": [normal.user_id]},
        )
        target0_watch_body = await self._expect_status(target0_watch, status=200)
        self._assert_watch_count(target0_watch_body, expected=1)

        clock.advance(1)
        target0_renew = await self._post(
            "/v1/presence/renew",
            session=targets[0],
            json={"device_id": "t-0", "ttl_seconds": 30},
        )
        await self._expect_status(target0_renew, status=200)

        deadline = asyncio.get_running_loop().time() + 1
        update = await recv_json_until(normal_ws, deadline=deadline, predicate=lambda msg: msg.get("t") == "presence.update")
        self._assert_presence_update_shape(update)

        target1_watch = await self._post(
            "/v1/presence/watch",
            session=targets[1],
            json={"contacts": [normal.user_id]},
        )
        target1_watch_body = await self._expect_status(target1_watch, status=200)
        self._assert_watch_count(target1_watch_body, expected=1)

        target1_lease = await self._post(
            "/v1/presence/lease",
            session=targets[1],
            json={"device_id": "t-1", "ttl_seconds": 30},
        )
        await self._expect_status(target1_lease, status=200)

        await self._next_presence_update(normal_ws)

        target1_ws = await self._start_ws("target-1", "t-1")
        normal_lease = await self._post(
            "/v1/presence/lease",
            session=normal,
            json={"device_id": "normal-device", "ttl_seconds": 30},
        )
        await self._expect_status(normal_lease, status=200)
        await self._next_presence_update(target1_ws)

        block_target1 = await self._post(
            "/v1/presence/block",
            session=normal,
            json={"contacts": [target_ids[1]]},
        )
        block_payload = await self._expect_status(block_target1, status=200)
        self._assert_block_count(block_payload, expected=1)

        clock.advance(1)
        target1_renew = await self._post(
            "/v1/presence/renew",
            session=targets[1],
            json={"device_id": "t-1", "ttl_seconds": 30},
        )
        await self._expect_status(target1_renew, status=200)
        await assert_no_app_messages(normal_ws, timeout=0.5)

        clock.advance(1)
        normal_renew = await self._post(
            "/v1/presence/renew",
            session=normal,
            json={"device_id": "normal-device", "ttl_seconds": 30},
        )
        await self._expect_status(normal_renew, status=200)
        await assert_no_app_messages(target1_ws, timeout=0.5)

        unblock_target1 = await self._post(
            "/v1/presence/unblock",
            session=normal,
            json={"contacts": [target_ids[1]]},
        )
        unblock_payload = await self._expect_status(unblock_target1, status=200)
        self._assert_block_count(unblock_payload, expected=0)

        clock.advance(1)
        target1_renew_again = await self._post(
            "/v1/presence/renew",
            session=targets[1],
            json={"device_id": "t-1", "ttl_seconds": 30},
        )
        await self._expect_status(target1_renew_again, status=200)

        await self._next_presence_update(normal_ws)

        clock.advance(1)
        normal_renew_again = await self._post(
            "/v1/presence/renew",
            session=normal,
            json={"device_id": "normal-device", "ttl_seconds": 30},
        )
        await self._expect_status(normal_renew_again, status=200)
        await self._next_presence_update(target1_ws)

        await target1_ws.close()
        await normal_ws.close()


if __name__ == "__main__":
    unittest.main()
