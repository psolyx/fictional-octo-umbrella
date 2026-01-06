import base64
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from gateway.social import canonical_event_bytes
from gateway.ws_transport import create_app

try:
    from nacl.signing import SigningKey
except ImportError as exc:  # pragma: no cover - dependencies enforced in gateway setup
    raise RuntimeError("PyNaCl must be installed for social tests") from exc


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class SocialEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.signing_key = SigningKey.generate()
        self.user_id = _b64url(self.signing_key.verify_key.encode())
        self.app = create_app(db_path=str(tempfile.NamedTemporaryFile(delete=False).name))
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        start_resp = await self.client.post(
            "/v1/session/start",
            json={"auth_token": f"Bearer {self.user_id}", "device_id": "device"},
        )
        self.assertEqual(start_resp.status, 200)
        ready = await start_resp.json()
        self.session_token = ready["session_token"]

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    def _sig(self, prev_hash, ts_ms: int, kind: str, payload: dict) -> str:
        canonical = canonical_event_bytes(
            user_id=self.user_id, prev_hash=prev_hash, ts_ms=ts_ms, kind=kind, payload=payload
        )
        signature = self.signing_key.sign(canonical).signature
        return _b64url(signature)

    async def _publish(self, body: dict) -> dict:
        resp = await self.client.post(
            "/v1/social/events",
            json=body,
            headers={"Authorization": f"Bearer {self.session_token}"},
        )
        result = await resp.json()
        return {"status": resp.status, "body": result}

    async def test_append_and_chain(self):
        first_payload = {"text": "hello"}
        first_sig = self._sig(None, 1, "post", first_payload)
        first = await self._publish(
            {"prev_hash": None, "ts_ms": 1, "kind": "post", "payload": first_payload, "sig_b64": first_sig}
        )
        self.assertEqual(first["status"], 200)
        first_hash = first["body"]["event_hash"]

        second_payload = {"text": "world"}
        second_sig = self._sig(first_hash, 2, "post", second_payload)
        second = await self._publish(
            {
                "prev_hash": first_hash,
                "ts_ms": 2,
                "kind": "post",
                "payload": second_payload,
                "sig_b64": second_sig,
            }
        )
        self.assertEqual(second["status"], 200)
        self.assertEqual(second["body"]["prev_hash"], first_hash)

        get_resp = await self.client.get(
            "/v1/social/events",
            params={"user_id": self.user_id, "limit": "10"},
        )
        self.assertEqual(get_resp.status, 200)
        body = await get_resp.json()
        self.assertEqual(len(body["events"]), 2)
        cache_control = get_resp.headers.get("Cache-Control", "")
        self.assertIn("public", cache_control)
        self.assertIn("max-age=30", cache_control)
        self.assertIn("ETag", get_resp.headers)

    async def test_rejects_invalid_signature_and_prev_hash(self):
        payload = {"text": "hi"}
        sig = self._sig(None, 1, "post", payload)
        bad_sig_body = payload | {"extra": True}
        bad_sig = await self._publish(
            {"prev_hash": None, "ts_ms": 1, "kind": "post", "payload": bad_sig_body, "sig_b64": sig}
        )
        self.assertEqual(bad_sig["status"], 400)

        good_sig = self._sig(None, 2, "post", payload)
        good = await self._publish(
            {"prev_hash": None, "ts_ms": 2, "kind": "post", "payload": payload, "sig_b64": good_sig}
        )
        self.assertEqual(good["status"], 200)
        head_hash = good["body"]["event_hash"]

        wrong_prev_sig = self._sig("bogus", 3, "post", payload)
        wrong_prev = await self._publish(
            {"prev_hash": "bogus", "ts_ms": 3, "kind": "post", "payload": payload, "sig_b64": wrong_prev_sig}
        )
        self.assertEqual(wrong_prev["status"], 400)
        self.assertEqual(wrong_prev["body"]["code"], "invalid_request")

        wrong_sig = self._sig("bogus", 4, "post", payload)
        fork_attempt = await self._publish(
            {"prev_hash": "bogus", "ts_ms": 4, "kind": "post", "payload": payload, "sig_b64": wrong_sig}
        )
        self.assertEqual(fork_attempt["status"], 400)
