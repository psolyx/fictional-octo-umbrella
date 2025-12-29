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

    async def _start_ws(self, device_id: str):
        ws = await self.client.ws_connect("/v1/ws")
        await ws.send_json({"v": 1, "t": "session.start", "id": "start", "body": {"auth_token": "t", "device_id": device_id}})
        await ws.receive_json()
        return ws

    async def test_lease_clamps_and_sets_online(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(), now_func=clock.now)
        await self._setup_app(presence)
        runtime = self.app["runtime"]
        session = runtime.sessions.create("d1")

        resp = await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "d1", "ttl_seconds": 10000},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        body = await resp.json()

        self.assertEqual(resp.status, 200)
        expected_exp = clock.now() + presence.config.max_ttl_seconds * 1000
        self.assertEqual(body["expires_at"], expected_exp)
        self.assertIn("d1", presence._leases)

    async def test_expiration_emits_offline(self):
        clock = FakeClock()
        config = PresenceConfig(max_ttl_seconds=5, min_ttl_seconds=1, watch_mutations_per_min=100, renews_per_min=100)
        presence = Presence(config, now_func=clock.now)
        await self._setup_app(presence)
        runtime = self.app["runtime"]
        session_target = runtime.sessions.create("d1")
        session_watcher = runtime.sessions.create("d2")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["d1"]},
            headers={"Authorization": f"Bearer {session_watcher.session_token}"},
        )
        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["d2"]},
            headers={"Authorization": f"Bearer {session_target.session_token}"},
        )

        watcher_ws = await self._start_ws("d2")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "d1", "ttl_seconds": 2},
            headers={"Authorization": f"Bearer {session_target.session_token}"},
        )

        online = await asyncio.wait_for(watcher_ws.receive_json(), timeout=1)
        self.assertEqual(online["t"], "presence.update")
        self.assertEqual(online["body"]["status"], "online")

        clock.advance(3)
        presence.expire()

        offline = await asyncio.wait_for(watcher_ws.receive_json(), timeout=1)
        self.assertEqual(offline["body"]["status"], "offline")
        await watcher_ws.close()

    async def test_watchlist_cap_enforced(self):
        config = PresenceConfig(max_watchlist_size=2, watch_mutations_per_min=100)
        presence = Presence(config)
        await self._setup_app(presence)
        runtime = self.app["runtime"]
        session = runtime.sessions.create("d1")

        resp = await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["u1", "u2", "u3"]},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        self.assertEqual(resp.status, 429)
        body = await resp.json()
        self.assertEqual(body["code"], "limit_exceeded")

    async def test_per_target_watcher_cap(self):
        config = PresenceConfig(max_watchers_per_target=1, watch_mutations_per_min=100)
        presence = Presence(config)
        await self._setup_app(presence)
        runtime = self.app["runtime"]
        watcher1 = runtime.sessions.create("d1")
        watcher2 = runtime.sessions.create("d2")

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
        config = PresenceConfig(renews_per_min=1)
        presence = Presence(config)
        await self._setup_app(presence)
        runtime = self.app["runtime"]
        session = runtime.sessions.create("d1")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "d1", "ttl_seconds": 10},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        resp = await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "d1", "ttl_seconds": 10},
            headers={"Authorization": f"Bearer {session.session_token}"},
        )
        self.assertEqual(resp.status, 429)

    async def test_mutual_watch_gating(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)
        runtime = self.app["runtime"]
        target_session = runtime.sessions.create("d1")
        watcher_session = runtime.sessions.create("d2")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["d1"]},
            headers={"Authorization": f"Bearer {watcher_session.session_token}"},
        )

        watcher_ws = await self._start_ws("d2")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "d1", "ttl_seconds": 2},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(watcher_ws.receive_json(), timeout=0.5)

        await watcher_ws.close()

    async def test_invisible_mode_suppresses_updates(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)
        runtime = self.app["runtime"]
        target_session = runtime.sessions.create("d1")
        watcher_session = runtime.sessions.create("d2")

        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["d1"]},
            headers={"Authorization": f"Bearer {watcher_session.session_token}"},
        )
        await self.client.post(
            "/v1/presence/watch",
            json={"contacts": ["d2"]},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        watcher_ws = await self._start_ws("d2")

        await self.client.post(
            "/v1/presence/lease",
            json={"device_id": "d1", "ttl_seconds": 2, "invisible": True},
            headers={"Authorization": f"Bearer {target_session.session_token}"},
        )

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(watcher_ws.receive_json(), timeout=0.5)

        await watcher_ws.close()


if __name__ == "__main__":
    unittest.main()
