import base64
import os
import tempfile
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from gateway.crypto_ed25519 import generate_keypair, sign
from gateway.social import canonical_event_bytes
from gateway.ws_transport import RUNTIME_KEY, create_app


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class AbuseControlsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._env = mock.patch.dict(
            os.environ,
            {
                "GATEWAY_CONV_SENDS_PER_MIN": "2",
                "GATEWAY_SOCIAL_PUBLISHES_PER_MIN": "1",
                "GATEWAY_DMS_CREATES_PER_MIN": "1",
                "GATEWAY_MAX_ENV_B64_LEN": "12",
                "GATEWAY_MAX_SOCIAL_EVENT_BYTES": "4096",
            },
            clear=False,
        )
        self._env.start()
        self.app = create_app(db_path=str(tempfile.NamedTemporaryFile(delete=False).name))
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self._env.stop()

    async def _session(self, user_id: str, device_id: str) -> str:
        response = await self.client.post(
            "/v1/session/start",
            json={"auth_token": f"Bearer {user_id}", "device_id": device_id},
        )
        self.assertEqual(response.status, 200)
        return str((await response.json())["session_token"])

    async def _create_dm(self, token: str, peer_user_id: str, conv_id: str = "dm_test"):
        return await self.client.post(
            "/v1/dms/create",
            headers={"Authorization": f"Bearer {token}"},
            json={"peer_user_id": peer_user_id, "conv_id": conv_id},
        )

    async def _send_conv(self, token: str, conv_id: str, msg_id: str, env: str):
        return await self.client.post(
            "/v1/inbox",
            headers={"Authorization": f"Bearer {token}"},
            json={"v": 1, "t": "conv.send", "body": {"conv_id": conv_id, "msg_id": msg_id, "env": env}},
        )

    async def test_dm_create_forbidden_when_blocked(self):
        alice = await self._session("u_alice", "d_alice")
        bob = await self._session("u_bob", "d_bob")
        block_response = await self.client.post(
            "/v1/presence/block",
            headers={"Authorization": f"Bearer {bob}"},
            json={"contacts": ["u_alice"]},
        )
        self.assertEqual(block_response.status, 200)

        response = await self._create_dm(alice, "u_bob", conv_id="dm_blocked")
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json()).get("code"), "forbidden")

    async def test_dm_send_forbidden_when_blocked(self):
        alice = await self._session("u_alice", "d_alice")
        bob = await self._session("u_bob", "d_bob")
        create_response = await self._create_dm(alice, "u_bob", conv_id="dm_blocked_send")
        self.assertEqual(create_response.status, 200)

        block_response = await self.client.post(
            "/v1/presence/block",
            headers={"Authorization": f"Bearer {bob}"},
            json={"contacts": ["u_alice"]},
        )
        self.assertEqual(block_response.status, 200)

        response = await self._send_conv(alice, "dm_blocked_send", "msg_1", "YQ==")
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json()).get("code"), "forbidden")

    async def test_conv_send_rate_limited_returns_429(self):
        alice = await self._session("u_alice", "d_alice")
        create_response = await self._create_dm(alice, "u_bob", conv_id="dm_rate_send")
        self.assertEqual(create_response.status, 200)

        first = await self._send_conv(alice, "dm_rate_send", "msg_1", "YQ==")
        second = await self._send_conv(alice, "dm_rate_send", "msg_2", "Yg==")
        third = await self._send_conv(alice, "dm_rate_send", "msg_3", "Yw==")
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)
        self.assertEqual(third.status, 429)
        self.assertEqual((await third.json()).get("code"), "rate_limited")

    async def test_social_publish_rate_limited_returns_429(self):
        seed, public_key = generate_keypair()
        user_id = _b64url(public_key)
        token = await self._session(user_id, "d_social")

        payload = {"value": "ok"}
        ts_ms = 10
        canonical = canonical_event_bytes(
            user_id=user_id,
            prev_hash=None,
            ts_ms=ts_ms,
            kind="username",
            payload=payload,
        )
        sig_b64 = _b64url(sign(seed, canonical))
        first = await self.client.post(
            "/v1/social/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"prev_hash": None, "ts_ms": ts_ms, "kind": "username", "payload": payload, "sig_b64": sig_b64},
        )
        self.assertEqual(first.status, 200)

        second = await self.client.post(
            "/v1/social/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"prev_hash": None, "ts_ms": ts_ms + 1, "kind": "username", "payload": payload, "sig_b64": sig_b64},
        )
        self.assertEqual(second.status, 429)
        self.assertEqual((await second.json()).get("code"), "rate_limited")


    async def test_presence_blocklist_returns_sorted_self_only(self):
        alice = await self._session("u_alice", "d_alice")
        await self.client.post(
            "/v1/presence/block",
            headers={"Authorization": f"Bearer {alice}"},
            json={"contacts": ["u_charlie", "u_bob"]},
        )
        response = await self.client.get(
            "/v1/presence/blocklist",
            headers={"Authorization": f"Bearer {alice}"},
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload.get("blocked"), ["u_bob", "u_charlie"])

    async def test_env_size_cap_rejects_large_env(self):
        alice = await self._session("u_alice", "d_alice")
        create_response = await self._create_dm(alice, "u_bob", conv_id="dm_env_cap")
        self.assertEqual(create_response.status, 200)

        response = await self._send_conv(alice, "dm_env_cap", "msg_big", "A" * 20)
        self.assertEqual(response.status, 400)
        payload = await response.json()
        self.assertEqual(payload.get("code"), "invalid_request")
        self.assertEqual(payload.get("message"), "env too large")

    async def test_social_size_cap_rejects_large_payload(self):
        self.app[RUNTIME_KEY].max_social_event_bytes = 140
        seed, public_key = generate_keypair()
        user_id = _b64url(public_key)
        token = await self._session(user_id, "d_social")
        payload = {"value": "x" * 400}
        ts_ms = 20
        canonical = canonical_event_bytes(
            user_id=user_id,
            prev_hash=None,
            ts_ms=ts_ms,
            kind="username",
            payload=payload,
        )
        sig_b64 = _b64url(sign(seed, canonical))
        response = await self.client.post(
            "/v1/social/events",
            headers={"Authorization": f"Bearer {token}"},
            json={"prev_hash": None, "ts_ms": ts_ms, "kind": "username", "payload": payload, "sig_b64": sig_b64},
        )
        self.assertEqual(response.status, 400)
        payload_json = await response.json()
        self.assertEqual(payload_json.get("code"), "invalid_request")
        self.assertEqual(payload_json.get("message"), "social event too large")


if __name__ == "__main__":
    unittest.main()
