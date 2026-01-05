import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import importlib
import importlib.metadata

EXPECTED_AIOHTTP_VERSION = "3.13.2"

_aiohttp_spec = importlib.util.find_spec("aiohttp")
if _aiohttp_spec is None:
    raise RuntimeError("aiohttp must be installed for gateway social tests")

from aiohttp.test_utils import TestClient, TestServer

_installed_aiohttp = importlib.metadata.version("aiohttp")
if _installed_aiohttp != EXPECTED_AIOHTTP_VERSION:
    raise RuntimeError(
        f"Expected aiohttp=={EXPECTED_AIOHTTP_VERSION} for gateway social tests, found {_installed_aiohttp}"
    )

from gateway.social import canonical_bytes, compute_event_id, derive_user_id
from gateway.ws_transport import create_app
TEST_SEED_B64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
_SEED_METADATA: dict | None = None
_GO_AVAILABLE = shutil.which("go") is not None


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        candidate = parent if parent.is_dir() else parent.parent
        tool_dir = candidate / "tools" / "polycentric_ed25519"
        if tool_dir.is_dir():
            return candidate
    raise RuntimeError("could not locate repo root")


def _sign(canonical: bytes) -> dict:
    tool_dir = _repo_root() / "tools" / "polycentric_ed25519"
    cmd = ["go", "run", "-mod=vendor", "./cmd/polycentric-ed25519", "sign", "--seed-b64", TEST_SEED_B64]
    env = {
        **os.environ,
        "GOTOOLCHAIN": "local",
        "GOFLAGS": "-mod=vendor",
    }
    result = subprocess.run(cmd, cwd=str(tool_dir), input=canonical, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8"))
    return json.loads(result.stdout.decode("utf-8"))


def _build_event(ts_ms: int, text: str) -> dict:
    global _SEED_METADATA
    if _SEED_METADATA is None:
        _SEED_METADATA = _sign(b"")
    user_id = derive_user_id(_SEED_METADATA["pub_key_b64"])
    body = {"text": text}
    canonical = canonical_bytes({"v": 1, "user_id": user_id, "ts_ms": ts_ms, "kind": "post", "body": body})
    signature = _sign(canonical)
    event_id = compute_event_id(canonical)
    return {
        "v": 1,
        "user_id": user_id,
        "ts_ms": ts_ms,
        "kind": "post",
        "body": body,
        "pub_key": signature["pub_key_b64"],
        "sig": signature["sig_b64"],
        "event_id": event_id,
    }


@unittest.skipUnless(_GO_AVAILABLE, "Go toolchain required for social signing")
class SocialEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "social.db"
        self.app = create_app(db_path=str(db_path))
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()
        self.tmpdir.cleanup()

    async def test_publish_and_get(self):
        event = _build_event(1, "hello")
        resp = await self.client.post("/v1/social/event", json=event)
        self.assertEqual(resp.status, 200)
        stored = await resp.json()
        self.assertEqual(stored["event_id"], event["event_id"])

        get_resp = await self.client.get(f"/v1/social/event/{event['event_id']}")
        self.assertEqual(get_resp.status, 200)
        self.assertEqual(get_resp.headers.get("Cache-Control"), "public, max-age=31536000, immutable")
        fetched = await get_resp.json()
        self.assertEqual(fetched["body"], event["body"])

    async def test_invalid_signature_rejected(self):
        event = _build_event(2, "bad")
        event["sig"] = "invalid"
        resp = await self.client.post("/v1/social/event", json=event)
        self.assertEqual(resp.status, 400)

    async def test_duplicate_publish_is_idempotent(self):
        event = _build_event(3, "dup")
        first = await self.client.post("/v1/social/event", json=event)
        self.assertEqual(first.status, 200)
        second = await self.client.post("/v1/social/event", json=event)
        self.assertEqual(second.status, 200)
        feed_resp = await self.client.get(f"/v1/social/feed?user_id={event['user_id']}&limit=10")
        feed = await feed_resp.json()
        self.assertEqual(len(feed["events"]), 1)

    async def test_cursor_pagination_and_cache_headers(self):
        events = [_build_event(10, "one"), _build_event(20, "two"), _build_event(30, "three")]
        for ev in events:
            resp = await self.client.post("/v1/social/event", json=ev)
            self.assertEqual(resp.status, 200)

        first_page = await self.client.get(f"/v1/social/feed?user_id={events[0]['user_id']}&limit=2")
        self.assertEqual(first_page.headers.get("Cache-Control"), "public, max-age=30")
        first_data = await first_page.json()
        self.assertEqual(len(first_data["events"]), 2)
        self.assertIsNotNone(first_data["cursor"])

        second_page = await self.client.get(
            f"/v1/social/feed?user_id={events[0]['user_id']}&cursor={first_data['cursor']}"
        )
        self.assertEqual(second_page.headers.get("Cache-Control"), "public, max-age=31536000, immutable")
        second_data = await second_page.json()
        self.assertEqual(len(second_data["events"]), 1)
        self.assertIsNone(second_data["cursor"])


if __name__ == "__main__":
    unittest.main()
