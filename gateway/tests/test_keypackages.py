import importlib
import importlib.metadata
import unittest

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway HTTP tests")

from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway HTTP tests, found {_installed_aiohttp}"
    )

from gateway.ws_transport import create_app


class KeyPackageHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(ping_interval_s=3600)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        runtime = self.app["runtime"]
        self.user_id = "user-1"
        self.device_id = "device-1"
        session = runtime.sessions.create(self.user_id, self.device_id)
        self.headers = {"Authorization": f"Bearer {session.session_token}"}

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_publish_and_fetch_one_time_use(self):
        publish = await self.client.post(
            "/v1/keypackages",
            json={"device_id": self.device_id, "keypackages": ["kp1", "kp2"]},
            headers=self.headers,
        )
        self.assertEqual(publish.status, 200)

        fetch_one = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": self.user_id, "count": 1},
            headers=self.headers,
        )
        body_one = await fetch_one.json()
        self.assertEqual(body_one["keypackages"], ["kp1"])

        fetch_two = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": self.user_id, "count": 2},
            headers=self.headers,
        )
        body_two = await fetch_two.json()
        self.assertEqual(body_two["keypackages"], ["kp2"])

        fetch_empty = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": self.user_id, "count": 2},
            headers=self.headers,
        )
        body_empty = await fetch_empty.json()
        self.assertEqual(body_empty["keypackages"], [])

    async def test_fetch_across_devices_for_user(self):
        runtime = self.app["runtime"]
        second_session = runtime.sessions.create(self.user_id, "device-2")
        second_headers = {"Authorization": f"Bearer {second_session.session_token}"}

        await self.client.post(
            "/v1/keypackages",
            json={"device_id": self.device_id, "keypackages": ["kp1"]},
            headers=self.headers,
        )
        await self.client.post(
            "/v1/keypackages",
            json={"device_id": "device-2", "keypackages": ["kp2"]},
            headers=second_headers,
        )

        fetch = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": self.user_id, "count": 5},
            headers=self.headers,
        )
        body = await fetch.json()
        self.assertEqual(body["keypackages"], ["kp1", "kp2"])

    async def test_rotate_revokes_unissued_and_accepts_replacements(self):
        await self.client.post(
            "/v1/keypackages",
            json={"device_id": self.device_id, "keypackages": ["old1", "old2"]},
            headers=self.headers,
        )

        runtime = self.app["runtime"]
        second_session = runtime.sessions.create(self.user_id, "device-2")
        second_headers = {"Authorization": f"Bearer {second_session.session_token}"}
        await self.client.post(
            "/v1/keypackages",
            json={"device_id": "device-2", "keypackages": ["other"]},
            headers=second_headers,
        )

        rotate = await self.client.post(
            "/v1/keypackages/rotate",
            json={"device_id": self.device_id, "revoke": True, "replacement": ["new1"]},
            headers=self.headers,
        )
        self.assertEqual(rotate.status, 200)

        fetch = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": self.user_id, "count": 5},
            headers=self.headers,
        )
        body = await fetch.json()
        self.assertIn("new1", body["keypackages"])
        self.assertIn("other", body["keypackages"])

        fetch_again = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": self.user_id, "count": 5},
            headers=self.headers,
        )
        body_again = await fetch_again.json()
        self.assertEqual(body_again["keypackages"], [])


if __name__ == "__main__":
    unittest.main()
