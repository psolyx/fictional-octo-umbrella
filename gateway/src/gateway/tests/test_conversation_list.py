import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from gateway.ws_transport import RUNTIME_KEY, create_app


class ConversationListTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app(db_path=str(tempfile.NamedTemporaryFile(delete=False).name))
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def _session(self, user_id: str, device_id: str) -> str:
        response = await self.client.post(
            "/v1/session/start",
            json={"auth_token": f"Bearer {user_id}", "device_id": device_id},
        )
        self.assertEqual(response.status, 200)
        body = await response.json()
        return str(body["session_token"])

    async def _create_room(self, token: str, conv_id: str, members: list[str]) -> None:
        response = await self.client.post(
            "/v1/rooms/create",
            headers={"Authorization": f"Bearer {token}"},
            json={"conv_id": conv_id, "members": members},
        )
        self.assertEqual(response.status, 200)

    async def _send_inbox(
        self,
        token: str,
        *,
        conv_id: str,
        msg_id: str,
        env: str,
        ts_ms: int,
    ) -> None:
        response = await self.client.post(
            "/v1/inbox",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "v": 1,
                "t": "conv.send",
                "body": {
                    "conv_id": conv_id,
                    "msg_id": msg_id,
                    "env": env,
                    "ts": ts_ms,
                },
            },
        )
        self.assertEqual(response.status, 200)

    async def test_list_requires_auth(self):
        response = await self.client.get("/v1/conversations")
        self.assertEqual(response.status, 401)

    async def test_conversation_list_membership_order_and_roster_bound(self):
        alice_token = await self._session("u_alice", "d_alice")
        bob_token = await self._session("u_bob", "d_bob")

        await self._create_room(alice_token, "conv_b", ["u_bob"])
        await self._create_room(alice_token, "conv_a", ["u_bob"])

        large_members = [f"u_member_{idx:02d}" for idx in range(21)]
        await self._create_room(alice_token, "conv_big", large_members)

        runtime = self.app[RUNTIME_KEY]
        with runtime.backend.lock:
            runtime.backend.connection.execute("UPDATE conversations SET created_at_ms=300 WHERE conv_id='conv_big'")
            runtime.backend.connection.execute("UPDATE conversations SET created_at_ms=200 WHERE conv_id='conv_a'")
            runtime.backend.connection.execute("UPDATE conversations SET created_at_ms=200 WHERE conv_id='conv_b'")

        bob_response = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(bob_response.status, 200)
        bob_items = (await bob_response.json())["items"]
        self.assertEqual([item["conv_id"] for item in bob_items], ["conv_a", "conv_b"])
        self.assertEqual([item["role"] for item in bob_items], ["member", "member"])

        alice_response = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        self.assertEqual(alice_response.status, 200)
        alice_items = (await alice_response.json())["items"]
        self.assertEqual([item["conv_id"] for item in alice_items], ["conv_a", "conv_b", "conv_big"])

        for item in alice_items[:2]:
            self.assertEqual(item["member_count"], 2)
            self.assertIn("members", item)
            self.assertEqual(item["members"], sorted(item["members"]))

        big_item = alice_items[2]
        self.assertEqual(big_item["member_count"], 22)
        self.assertNotIn("members", big_item)

    async def test_conversation_list_includes_log_bounds_and_latest_ts(self):
        alice_token = await self._session("u_alice", "d_alice")
        await self._create_room(alice_token, "conv_with_events", [])
        await self._create_room(alice_token, "conv_empty", [])

        await self._send_inbox(
            alice_token,
            conv_id="conv_with_events",
            msg_id="m1",
            env="ZW52MQ==",
            ts_ms=1000,
        )
        await self._send_inbox(
            alice_token,
            conv_id="conv_with_events",
            msg_id="m2",
            env="ZW52Mg==",
            ts_ms=2000,
        )

        response = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        self.assertEqual(response.status, 200)
        by_conv_id = {item["conv_id"]: item for item in (await response.json())["items"]}

        with_events = by_conv_id["conv_with_events"]
        self.assertEqual(with_events["earliest_seq"], 1)
        self.assertEqual(with_events["latest_seq"], 2)
        self.assertEqual(with_events["latest_ts_ms"], 2000)

        empty = by_conv_id["conv_empty"]
        self.assertIsNone(empty["earliest_seq"])
        self.assertIsNone(empty["latest_seq"])
        self.assertIsNone(empty["latest_ts_ms"])


if __name__ == "__main__":
    unittest.main()
