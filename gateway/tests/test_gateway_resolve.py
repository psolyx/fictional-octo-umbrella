import importlib
import importlib.metadata
import json
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


class GatewayResolveTests(unittest.IsolatedAsyncioTestCase):
    async def _start_client(self, **kwargs):
        app = create_app(ping_interval_s=3600, **kwargs)
        server = TestServer(app)
        await server.start_server()
        client = TestClient(server)
        await client.start_server()
        return app, server, client

    async def _cleanup(self, server: TestServer, client: TestClient) -> None:
        await client.close()
        await server.close()

    async def test_resolves_local_gateway(self):
        _, server, client = await self._start_client(gateway_public_url="https://local.example")
        try:
            response = await client.get("/v1/gateways/resolve", params={"gateway_id": "gw_local"})
            body = await response.json()
            self.assertEqual(response.status, 200)
            self.assertEqual(body, {"gateway_id": "gw_local", "gateway_url": "https://local.example"})
        finally:
            await self._cleanup(server, client)

    async def test_resolves_from_directory(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            directory_path = handle.name
            json.dump({"gateways": {"gw_remote": "https://remote.example"}}, handle)

        try:
            _, server, client = await self._start_client(
                gateway_public_url="https://local.example", gateway_directory_path=directory_path
            )
            try:
                response = await client.get("/v1/gateways/resolve", params={"gateway_id": "gw_remote"})
                body = await response.json()
                self.assertEqual(response.status, 200)
                self.assertEqual(body, {"gateway_id": "gw_remote", "gateway_url": "https://remote.example"})
            finally:
                await self._cleanup(server, client)
        finally:
            os.unlink(directory_path)

    async def test_unknown_gateway_returns_404(self):
        _, server, client = await self._start_client(gateway_public_url="https://local.example")
        try:
            response = await client.get("/v1/gateways/resolve", params={"gateway_id": "gw_missing"})
            body = await response.json()
            self.assertEqual(response.status, 404)
            self.assertEqual(body["code"], "not_found")
        finally:
            await self._cleanup(server, client)

    async def test_missing_gateway_id_returns_400(self):
        _, server, client = await self._start_client(gateway_public_url="https://local.example")
        try:
            response = await client.get("/v1/gateways/resolve")
            body = await response.json()
            self.assertEqual(response.status, 400)
            self.assertEqual(body["code"], "invalid_request")
        finally:
            await self._cleanup(server, client)


if __name__ == "__main__":
    unittest.main()
