import unittest
import json

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


    async def test_session_logout_invalidates_token(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        session = await self._create_session('u_a', 'd1')

        logout_resp = await self.client.post(
            '/v1/session/logout',
            headers={'Authorization': f'Bearer {session.session_token}'},
        )
        self.assertEqual(logout_resp.status, 200)
        self.assertEqual(await logout_resp.json(), {'status': 'ok'})

        status_resp = await self.client.post(
            '/v1/presence/status',
            json={'contacts': []},
            headers={'Authorization': f'Bearer {session.session_token}'},
        )
        self.assertEqual(status_resp.status, 401)

    async def test_session_logout_all_invalidates_other_sessions_but_keeps_current_by_default(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        session_one = await self._create_session('u_a', 'd1')
        session_two = await self._create_session('u_a', 'd2')

        logout_all_resp = await self.client.post(
            '/v1/session/logout_all',
            json={},
            headers={'Authorization': f'Bearer {session_one.session_token}'},
        )
        self.assertEqual(logout_all_resp.status, 200)
        payload = await logout_all_resp.json()
        self.assertEqual(payload.get('status'), 'ok')
        self.assertTrue(payload.get('kept_current'))

        current_resp = await self.client.post(
            '/v1/presence/status',
            json={'contacts': []},
            headers={'Authorization': f'Bearer {session_one.session_token}'},
        )
        self.assertEqual(current_resp.status, 200)

        other_resp = await self.client.post(
            '/v1/presence/status',
            json={'contacts': []},
            headers={'Authorization': f'Bearer {session_two.session_token}'},
        )
        self.assertEqual(other_resp.status, 401)

    async def test_session_logout_all_include_self_revokes_current(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        session = await self._create_session('u_a', 'd1')

        logout_all_resp = await self.client.post(
            '/v1/session/logout_all',
            json={'include_self': True},
            headers={'Authorization': f'Bearer {session.session_token}'},
        )
        self.assertEqual(logout_all_resp.status, 200)

        status_resp = await self.client.post(
            '/v1/presence/status',
            json={'contacts': []},
            headers={'Authorization': f'Bearer {session.session_token}'},
        )
        self.assertEqual(status_resp.status, 401)

    async def test_session_list_shape_ordering_and_secret_redaction(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        current_session = await self._create_session('u_a', 'd_b')
        same_device_session = await self._create_session('u_a', 'd_b')
        other_device_session = await self._create_session('u_a', 'd_a')

        response = await self.client.get(
            '/v1/session/list',
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertIn('sessions', payload)
        self.assertIn('current_session_id', payload)
        self.assertIsInstance(payload['sessions'], list)
        self.assertIsInstance(payload['current_session_id'], str)

        self.assertEqual(len(payload['sessions']), 3)
        first = payload['sessions'][0]
        self.assertTrue(first['is_current'])
        self.assertEqual(first['device_id'], 'd_b')
        self.assertIsInstance(first['created_at_ms'], int)
        self.assertIsInstance(first['last_seen_at_ms'], int)
        self.assertGreaterEqual(first['last_seen_at_ms'], first['created_at_ms'])
        self.assertIsInstance(first['client_label'], str)
        self.assertLessEqual(len(first['client_label']), 32)
        session_keys = list(first.keys())
        self.assertEqual(session_keys, ['session_id', 'device_id', 'expires_at_ms', 'is_current', 'created_at_ms', 'last_seen_at_ms', 'client_label'])

        ordered_pairs = [(row['is_current'], row['device_id'], row['session_id']) for row in payload['sessions']]
        self.assertEqual(ordered_pairs, sorted(ordered_pairs, key=lambda row: (not row[0], row[1], row[2])))
        self.assertIn(payload['current_session_id'], [row['session_id'] for row in payload['sessions']])

        raw_json = json.dumps(payload)
        self.assertNotIn('session_token', raw_json)
        self.assertNotIn('resume_token', raw_json)
        self.assertNotIn(current_session.session_token, raw_json)
        self.assertNotIn(same_device_session.session_token, raw_json)
        self.assertNotIn(other_device_session.session_token, raw_json)
        self.assertNotIn(current_session.resume_token, raw_json)

        def _collect_scalar_values(value):
            if isinstance(value, dict):
                for nested in value.values():
                    yield from _collect_scalar_values(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    yield from _collect_scalar_values(nested)
                return
            yield str(value)

        values_blob = " ".join(_collect_scalar_values(payload))
        self.assertNotIn('st_', values_blob)
        self.assertNotIn('rt_', values_blob)

    async def test_session_revoke_by_session_id_invalidates_token(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        current_session = await self._create_session('u_a', 'd_a')
        target_session = await self._create_session('u_a', 'd_b')

        listed = await self.client.get(
            '/v1/session/list',
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        session_rows = (await listed.json())['sessions']
        target_id = [row['session_id'] for row in session_rows if row['device_id'] == 'd_b'][0]

        revoke_resp = await self.client.post(
            '/v1/session/revoke',
            json={'session_id': target_id},
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        self.assertEqual(revoke_resp.status, 200)
        payload = await revoke_resp.json()
        self.assertEqual(payload, {'status': 'ok', 'revoked': 1, 'revoked_session_ids': [target_id]})

        revoked_status = await self.client.post(
            '/v1/presence/status',
            json={'contacts': []},
            headers={'Authorization': f'Bearer {target_session.session_token}'},
        )
        self.assertEqual(revoked_status.status, 401)

    async def test_session_revoke_by_device_id_preserves_or_includes_current(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        current_session = await self._create_session('u_a', 'd_keep')
        same_device_other = await self._create_session('u_a', 'd_keep')
        same_device_more = await self._create_session('u_a', 'd_keep')

        revoke_resp = await self.client.post(
            '/v1/session/revoke',
            json={'device_id': 'd_keep'},
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        self.assertEqual(revoke_resp.status, 200)
        revoke_payload = await revoke_resp.json()
        self.assertEqual(revoke_payload['status'], 'ok')
        self.assertEqual(revoke_payload['revoked'], 2)
        self.assertEqual(revoke_payload['revoked_session_ids'], sorted(revoke_payload['revoked_session_ids']))

        current_status = await self.client.post(
            '/v1/presence/status',
            json={'contacts': []},
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        self.assertEqual(current_status.status, 200)

        for revoked in (same_device_other, same_device_more):
            resp = await self.client.post(
                '/v1/presence/status',
                json={'contacts': []},
                headers={'Authorization': f'Bearer {revoked.session_token}'},
            )
            self.assertEqual(resp.status, 401)

        include_self_resp = await self.client.post(
            '/v1/session/revoke',
            json={'device_id': 'd_keep', 'include_self': True},
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        self.assertEqual(include_self_resp.status, 200)
        self.assertEqual((await include_self_resp.json())['revoked'], 1)

        current_after = await self.client.post(
            '/v1/presence/status',
            json={'contacts': []},
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        self.assertEqual(current_after.status, 401)

    async def test_session_revoke_refuses_current_without_include_self(self):
        clock = FakeClock()
        await self._setup_app(Presence(PresenceConfig(), now_func=clock.now))
        current_session = await self._create_session('u_a', 'd_now')
        listed = await self.client.get(
            '/v1/session/list',
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        current_id = (await listed.json())['current_session_id']

        revoke_resp = await self.client.post(
            '/v1/session/revoke',
            json={'session_id': current_id},
            headers={'Authorization': f'Bearer {current_session.session_token}'},
        )
        self.assertEqual(revoke_resp.status, 400)
        self.assertEqual(
            await revoke_resp.json(),
            {
                'code': 'invalid_request',
                'message': 'refusing to revoke current session without include_self',
            },
        )


if __name__ == '__main__':
    unittest.main()
