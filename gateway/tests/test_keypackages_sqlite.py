import importlib
import importlib.metadata
import os
import tempfile
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


class KeyPackageSQLiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "gateway.db")
        self.server: TestServer | None = None
        self.client: TestClient | None = None

    async def asyncTearDown(self):
        if self.client:
            await self.client.close()
        if self.server:
            await self.server.close()
        self.tmpdir.cleanup()

    async def _start_server(self):
        app = create_app(ping_interval_s=3600, db_path=self.db_path)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        return app

    async def test_persistence_across_restart(self):
        app1 = await self._start_server()
        runtime1 = app1["runtime"]
        user_id = "user-sql"
        device_id = "device-sql"
        session = runtime1.sessions.create(user_id, device_id)
        headers = {"Authorization": f"Bearer {session.session_token}"}

        publish = await self.client.post(
            "/v1/keypackages",
            json={"device_id": device_id, "keypackages": ["persist1", "persist2"]},
            headers=headers,
        )
        self.assertEqual(publish.status, 200)

        await self.client.close()
        await self.server.close()
        self.client = None
        self.server = None

        await self._start_server()

        fetch_first = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": user_id, "count": 1},
            headers=headers,
        )
        body_first = await fetch_first.json()
        self.assertEqual(body_first["keypackages"], ["persist1"])

        fetch_second = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": user_id, "count": 5},
            headers=headers,
        )
        body_second = await fetch_second.json()
        self.assertEqual(body_second["keypackages"], ["persist2"])

        fetch_empty = await self.client.post(
            "/v1/keypackages/fetch",
            json={"user_id": user_id, "count": 5},
            headers=headers,
        )
        body_empty = await fetch_empty.json()
        self.assertEqual(body_empty["keypackages"], [])

    async def test_fetch_across_devices_sqlite(self):
        app = await self._start_server()
        runtime = app["runtime"]
        user_id = "user-sql"
        device_one = runtime.sessions.create(user_id, "device-1")
        device_two = runtime.sessions.create(user_id, "device-2")

        headers_one = {"Authorization": f"Bearer {device_one.session_token}"}
        headers_two = {"Authorization": f"Bearer {device_two.session_token}"}

        await self.client.post(
            "/v1/keypackages", json={"device_id": "device-1", "keypackages": ["a1"]}, headers=headers_one
        )
        await self.client.post(
            "/v1/keypackages", json={"device_id": "device-2", "keypackages": ["b1"]}, headers=headers_two
        )

        fetched = await self.client.post(
            "/v1/keypackages/fetch", json={"user_id": user_id, "count": 5}, headers=headers_one
        )
        body = await fetched.json()
        self.assertEqual(body["keypackages"], ["a1", "b1"])


if __name__ == "__main__":
    unittest.main()
