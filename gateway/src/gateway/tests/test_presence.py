import unittest

from aiohttp.test_utils import TestClient, TestServer

from gateway.presence import Presence, PresenceConfig
from gateway.ws_transport import RUNTIME_KEY, create_app


class FakeClock:
    def __init__(self, start_ms: int = 0) -> None:
        self.now_ms = start_ms

    def advance(self, seconds: float) -> None:
        self.now_ms += int(seconds * 1000)

    def now(self) -> int:
        return self.now_ms


class PresenceStatusTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_session(self, user_id: str, device_id: str):
        runtime = self.app[RUNTIME_KEY]
        return runtime.sessions.create(user_id, device_id)

    async def test_status_requires_auth(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        resp = await self.client.post('/v1/presence/status', json={'contacts': ['u_a']})
        self.assertEqual(resp.status, 401)

    async def test_status_gating_and_ordering(self):
        clock = FakeClock()
        presence = Presence(PresenceConfig(min_ttl_seconds=1), now_func=clock.now)
        await self._setup_app(presence)
        watcher = await self._create_session('watcher', 'w1')
        target = await self._create_session('target', 't1')

        await self.client.post('/v1/presence/watch', json={'contacts': ['target']}, headers={'Authorization': f'Bearer {watcher.session_token}'})
        await self.client.post('/v1/presence/watch', json={'contacts': ['watcher']}, headers={'Authorization': f'Bearer {target.session_token}'})
        await self.client.post('/v1/presence/lease', json={'device_id': 't1', 'ttl_seconds': 2}, headers={'Authorization': f'Bearer {target.session_token}'})

        resp = await self.client.post('/v1/presence/status', json={'contacts': ['u_z', 'target', 'u_a']}, headers={'Authorization': f'Bearer {watcher.session_token}'})
        payload = await resp.json()
        self.assertEqual([row['user_id'] for row in payload['statuses']], ['target', 'u_a', 'u_z'])
        statuses = {row['user_id']: row['status'] for row in payload['statuses']}
        self.assertEqual(statuses['target'], 'online')
        self.assertEqual(statuses['u_a'], 'unavailable')

        await self.client.post('/v1/presence/block', json={'contacts': ['target']}, headers={'Authorization': f'Bearer {watcher.session_token}'})
        blocked_resp = await self.client.post('/v1/presence/status', json={'contacts': ['target']}, headers={'Authorization': f'Bearer {watcher.session_token}'})
        self.assertEqual((await blocked_resp.json())['statuses'][0]['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
