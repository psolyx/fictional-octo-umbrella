import asyncio
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
from gateway.ws_transport import create_app


class FakeClock:
    def __init__(self, start_ms: int = 0) -> None:
        self.now_ms = start_ms

    def advance(self, seconds: float) -> None:
        self.now_ms += int(seconds * 1000)

    def now(self) -> int:
        return self.now_ms


class PresenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
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
        runtime = self.app["runtime"]
        return runtime.sessions.create(user_id, device_id)

    async def test_lease_clamps_and_sets_online(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(), now_func=clock.now)
        await self._setup_app(presence)
        session = await self._create_session("user-1", "d1")

        resp = await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "d1", "ttl_seconds": 10000},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        body = await resp.json()

        self.assertEqual(resp.status, 200)
        expected_exp = clock.now() + presence.config.max_ttl_seconds * 1000
        self.assertEqual(body["expires_at"], expected_exp)
        self.assertEqual(presence._leases["d1"].user_id, "user-1")

    async def test_multi_device_aggregation_and_offline_after_all_expire(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)

        target_session = await self._create_session("target", "t1")
        target_session_two = await self._create_session("target", "t2")
        watcher_session = await self._create_session("watcher", "w1")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher_session.session_token}"},
        )
        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["watcher"]},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        watcher_ws = await self._start_ws("watcher", "w1")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t1", "ttl_seconds": 2},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        online_first = await asyncio.wait_for(watcher_ws.receive_json(), timeout=1)
        self.assertEqual(online_first["body"]["status"], "online")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t2", "ttl_seconds": 4},
            headers={"Authorization": f"Bearer {target_session_two.session_token}"},
        )

        online_second = await asyncio.wait_for(watcher_ws.receive_json(), timeout=1)
        self.assertEqual(online_second["body"]["status"], "online")
        self.assertGreater(online_second["body"]["expires_at"], online_first["body"]["expires_at"])

        clock.advance(3)
        presence.expire()

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(watcher_ws.receive_json(), timeout=0.5)

        clock.advance(2)
        presence.expire()

        offline = await asyncio.wait_for(watcher_ws.receive_json(), timeout=1)
        self.assertEqual(offline["body"]["status"], "offline")
        await watcher_ws.close()

    async def test_fanout_to_all_watcher_devices(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)

        target_session = await self._create_session("target", "t1")
        watcher_session1 = await self._create_session("watcher", "w1")
        watcher_session2 = await self._create_session("watcher", "w2")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher_session1.session_token}"},
        )
        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["watcher"]},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        ws1 = await self._start_ws("watcher", "w1")
        ws2 = await self._start_ws("watcher", "w2")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t1", "ttl_seconds": 2},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        update1 = await asyncio.wait_for(ws1.receive_json(), timeout=1)
        update2 = await asyncio.wait_for(ws2.receive_json(), timeout=1)
        self.assertEqual(update1["body"]["status"], "online")
        self.assertEqual(update2["body"]["status"], "online")
        await ws1.close()
        await ws2.close()

    async def test_blocklist_prevents_updates_and_unblock_restores(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)

        target_session = await self._create_session("target", "t1")
        watcher_session1 = await self._create_session("watcher", "w1")
        watcher_session2 = await self._create_session("watcher", "w2")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher_session1.session_token}"},
        )
        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["watcher"]},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        ws1 = await self._start_ws("watcher", "w1")
        ws2 = await self._start_ws("watcher", "w2")

        block_resp = await self.client.post(
            "/v1/presence/block",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher_session1.session_token}"},
        )
        self.assertEqual(block_resp.status, 200)
        self.assertEqual((await block_resp.json())["blocked"], 1)

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t1", "ttl_seconds": 2},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ws1.receive_json(), timeout=0.5)
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(ws2.receive_json(), timeout=0.5)

        unblock_resp = await self.client.post(
            "/v1/presence/unblock",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher_session1.session_token}"},
        )
        self.assertEqual(unblock_resp.status, 200)
        self.assertEqual((await unblock_resp.json())["blocked"], 0)

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t1", "ttl_seconds": 3},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        update1 = await asyncio.wait_for(ws1.receive_json(), timeout=1)
        update2 = await asyncio.wait_for(ws2.receive_json(), timeout=1)
        self.assertEqual(update1["body"]["status"], "online")
        self.assertEqual(update2["body"]["status"], "online")

        await ws1.close()
        await ws2.close()

    async def test_mutual_watch_gating_user_level(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)
        target_session = await self._create_session("target", "t1")
        watcher_session = await self._create_session("watcher", "w1")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher_session.session_token}"},
        )

        watcher_ws = await self._start_ws("watcher", "w1")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t1", "ttl_seconds": 2},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(watcher_ws.receive_json(), timeout=0.5)

        await watcher_ws.close()

    async def test_invisible_mode_multi_device(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)
        target_session = await self._create_session("target", "t1")
        target_session_two = await self._create_session("target", "t2")
        watcher_session = await self._create_session("watcher", "w1")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher_session.session_token}"},
        )
        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["watcher"]},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        watcher_ws = await self._start_ws("watcher", "w1")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t1", "ttl_seconds": 3, "invisible": True},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(watcher_ws.receive_json(), timeout=0.5)

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "t2", "ttl_seconds": 2},
            headers={"Authorization": f"Bearer {target_session_two.session_token}"},
        )

        online = await asyncio.wait_for(watcher_ws.receive_json(), timeout=1)
        self.assertEqual(online["body"]["status"], "online")

        clock.advance(3)
        presence.expire()

        offline = await asyncio.wait_for(watcher_ws.receive_json(), timeout=1)
        self.assertEqual(offline["body"]["status"], "offline")
        await watcher_ws.close()

    async def test_watchlist_cap_enforced(self):
        presence = Presence(PresenceConfig(max_watchlist_size=2, watch_mutations_per_min=100))
        await self._setup_app(presence)
        session = await self._create_session("watcher", "w1")

        resp = await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["u1", "u2", "u3"]},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        self.assertEqual(resp.status, 429)
        body = await resp.json()
        self.assertEqual(body["code"], "limit_exceeded")

    async def test_per_target_watcher_cap(self):
        presence = Presence(PresenceConfig(max_watchers_per_target=1, watch_mutations_per_min=100))
        await self._setup_app(presence)
        watcher1 = await self._create_session("watcher1", "w1")
        watcher2 = await self._create_session("watcher2", "w2")

        first = await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher1.session_token}"},
        )
        self.assertEqual(first.status, 200)

        resp = await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["target"]},
            headers={"Authorization": f"Bearer {watcher2.session_token}"},
        )
        self.assertEqual(resp.status, 429)
        body = await resp.json()
        self.assertEqual(body["code"], "limit_exceeded")

    async def test_rate_limit_returns_429(self):
        presence = Presence(PresenceConfig(renews_per_min=1))
        await self._setup_app(presence)
        session = await self._create_session("watcher", "w1")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "w1", "ttl_seconds": 10},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        resp = await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "w1", "ttl_seconds": 10},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        self.assertEqual(resp.status, 429)


if __name__ == "__main__":
    unittest.main()
