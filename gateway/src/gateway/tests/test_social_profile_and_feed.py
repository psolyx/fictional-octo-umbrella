import base64
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from gateway.crypto_ed25519 import generate_keypair, sign
from gateway.social import canonical_event_bytes
from gateway.ws_transport import create_app


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class SocialProfileAndFeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user_seeds = {}
        self.head_by_user = {}
        self.alice = self._new_user()
        self.bob = self._new_user()
        self.carla = self._new_user()
        self.app = create_app(db_path=str(tempfile.NamedTemporaryFile(delete=False).name))
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.session_token = {}
        for user_id in (self.alice, self.bob, self.carla):
            start_resp = await self.client.post(
                "/v1/session/start",
                json={"auth_token": f"Bearer {user_id}", "device_id": f"device-{user_id[:6]}"},
            )
            self.assertEqual(start_resp.status, 200)
            self.session_token[user_id] = (await start_resp.json())["session_token"]

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    def _new_user(self) -> str:
        seed, public_key = generate_keypair()
        user_id = _b64url(public_key)
        self.user_seeds[user_id] = seed
        self.head_by_user[user_id] = None
        return user_id

    def _sig(self, user_id: str, ts_ms: int, kind: str, payload: dict) -> str:
        prev_hash = self.head_by_user[user_id]
        canonical = canonical_event_bytes(
            user_id=user_id,
            prev_hash=prev_hash,
            ts_ms=ts_ms,
            kind=kind,
            payload=payload,
        )
        return _b64url(sign(self.user_seeds[user_id], canonical))

    async def _publish(self, user_id: str, ts_ms: int, kind: str, payload: dict):
        prev_hash = self.head_by_user[user_id]
        response = await self.client.post(
            "/v1/social/events",
            headers={"Authorization": f"Bearer {self.session_token[user_id]}"},
            json={
                "prev_hash": prev_hash,
                "ts_ms": ts_ms,
                "kind": kind,
                "payload": payload,
                "sig_b64": self._sig(user_id, ts_ms, kind, payload),
            },
        )
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.head_by_user[user_id] = body["event_hash"]
        return body

    async def test_profile_resolution_is_last_writer_wins(self):
        await self._publish(self.alice, 10, "username", {"value": "alice-old"})
        await self._publish(self.alice, 40, "username", {"value": "alice-new"})
        await self._publish(self.alice, 15, "description", {"value": "hello"})
        await self._publish(self.alice, 20, "interests", {"value": "music, coding"})
        await self._publish(self.alice, 22, "follow", {"target_user_id": self.bob, "following": True})
        await self._publish(self.alice, 30, "post", {"value": "older"})
        await self._publish(self.alice, 31, "post", {"value": "newer"})

        response = await self.client.get("/v1/social/profile", params={"user_id": self.alice, "limit": "5"})
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["username"], "alice-new")
        self.assertEqual(body["description"], "hello")
        self.assertEqual(body["interests"], "music, coding")
        self.assertEqual(body["friends"], [self.bob])
        self.assertEqual([item["payload"]["value"] for item in body["latest_posts"]], ["newer", "older"])
        self.assertIn("ETag", response.headers)
        self.assertIn("Last-Modified", response.headers)

    async def test_follow_unfollow_changes_friends_and_feed(self):
        await self._publish(self.bob, 10, "post", {"value": "bob post"})
        await self._publish(self.carla, 11, "post", {"value": "carla post"})
        await self._publish(self.alice, 12, "post", {"value": "alice post"})
        await self._publish(self.alice, 13, "follow", {"target_user_id": self.bob, "following": True})

        first_feed = await self.client.get("/v1/social/feed", params={"user_id": self.alice, "limit": "10"})
        self.assertEqual(first_feed.status, 200)
        first_items = (await first_feed.json())["items"]
        self.assertEqual([item["payload"]["value"] for item in first_items], ["alice post", "bob post"])

        await self._publish(self.alice, 14, "follow", {"target_user_id": self.bob, "following": False})
        second_feed = await self.client.get("/v1/social/feed", params={"user_id": self.alice, "limit": "10"})
        self.assertEqual(second_feed.status, 200)
        second_items = (await second_feed.json())["items"]
        self.assertEqual([item["payload"]["value"] for item in second_items], ["alice post"])

        profile_response = await self.client.get("/v1/social/profile", params={"user_id": self.alice})
        self.assertEqual(profile_response.status, 200)
        self.assertEqual((await profile_response.json())["friends"], [])

    async def test_feed_order_and_cursor_are_deterministic(self):
        first = await self._publish(self.bob, 100, "post", {"value": "bob-100-a"})
        await self._publish(self.bob, 100, "post", {"value": "bob-100-b"})
        await self._publish(self.alice, 110, "follow", {"target_user_id": self.bob, "following": True})

        first_page_response = await self.client.get(
            "/v1/social/feed",
            params={"user_id": self.alice, "limit": "1"},
        )
        self.assertEqual(first_page_response.status, 200)
        first_page = await first_page_response.json()
        self.assertEqual(first_page["items"][0]["payload"]["value"], "bob-100-b")
        self.assertTrue(first_page["next_cursor"].startswith("100:"))

        second_page_response = await self.client.get(
            "/v1/social/feed",
            params={"user_id": self.alice, "limit": "5", "cursor": first_page["next_cursor"]},
        )
        self.assertEqual(second_page_response.status, 200)
        second_page = await second_page_response.json()
        self.assertEqual([item["payload"]["value"] for item in second_page["items"]], ["bob-100-a"])
        self.assertEqual(second_page["items"][0]["event_hash"], first["event_hash"])


if __name__ == "__main__":
    unittest.main()
