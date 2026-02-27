import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

ROOT_DIR = Path(__file__).resolve().parents[3]
GATEWAY_SRC = ROOT_DIR / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from cli_app.phase5_2_smoke_lite import (
    PHASE5_2_SMOKE_LITE_BEGIN,
    PHASE5_2_SMOKE_LITE_END,
    PHASE5_2_SMOKE_LITE_OK,
    run_smoke_lite_testclient,
)
from gateway.ws_transport import create_app


class Phase52SmokeLiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(db_path=str(tempfile.NamedTemporaryFile(delete=False).name))
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_smoke_lite_runner_and_markers(self):
        output = io.StringIO()
        exit_code = await run_smoke_lite_testclient(self.client, out=output)
        self.assertEqual(exit_code, 0)

        transcript = output.getvalue()
        self.assertIn(PHASE5_2_SMOKE_LITE_BEGIN, transcript)
        self.assertIn(PHASE5_2_SMOKE_LITE_OK, transcript)
        self.assertIn(PHASE5_2_SMOKE_LITE_END, transcript)
        self.assertIsNone(re.search(r"\bst_[A-Za-z0-9_-]{8,}\b", transcript))
        self.assertIsNone(re.search(r"\brt_[A-Za-z0-9_-]{8,}\b", transcript))


if __name__ == "__main__":
    unittest.main()
