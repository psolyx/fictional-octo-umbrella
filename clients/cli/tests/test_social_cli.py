import asyncio
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY_SRC = ROOT_DIR / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from cli_app import hello, identity_store
from gateway.ws_transport import create_app


class SocialCliTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.identity_dir = tempfile.TemporaryDirectory()
        self.identity_path = Path(self.identity_dir.name) / "identity.json"
        self.identity = identity_store.load_or_create_identity(self.identity_path)
        self.app = create_app(db_path=str(tempfile.NamedTemporaryFile(delete=False).name))
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.base_url = str(self.server.make_url(""))

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.identity_dir.cleanup()

    async def test_publish_and_fetch_roundtrip(self):
        payload_json = json.dumps({"text": "hi-cli"})
        publish_output = io.StringIO()
        exit_code = await asyncio.to_thread(
            hello.main,
            [
                "social",
                "publish",
                "--kind",
                "post",
                "--payload",
                payload_json,
                "--gateway-url",
                self.base_url,
                "--identity-path",
                str(self.identity_path),
            ],
            publish_output,
        )
        self.assertEqual(exit_code, 0)
        published = json.loads(publish_output.getvalue())
        self.assertEqual(published["payload"], {"text": "hi-cli"})

        fetch_output = io.StringIO()
        fetch_exit = await asyncio.to_thread(
            hello.main,
            [
                "social",
                "fetch",
                "--user_id",
                self.identity.social_public_key_b64,
                "--limit",
                "5",
                "--gateway-url",
                self.base_url,
                "--identity-path",
                str(self.identity_path),
            ],
            fetch_output,
        )
        self.assertEqual(fetch_exit, 0)
        events = json.loads(fetch_output.getvalue())
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["text"], "hi-cli")
