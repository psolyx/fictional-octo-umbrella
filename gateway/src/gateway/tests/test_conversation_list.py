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

    async def test_mark_read_and_unread_counts_follow_server_state(self):
        alice_token = await self._session("u_alice", "d_alice")
        await self._create_room(alice_token, "conv_reads", [])

        await self._send_inbox(
            alice_token,
            conv_id="conv_reads",
            msg_id="m1",
            env="ZW52MQ==",
            ts_ms=1000,
        )
        await self._send_inbox(
            alice_token,
            conv_id="conv_reads",
            msg_id="m2",
            env="ZW52Mg==",
            ts_ms=2000,
        )

        initial_list = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        self.assertEqual(initial_list.status, 200)
        initial_item = (await initial_list.json())["items"][0]
        self.assertEqual(initial_item["unread_count"], 2)
        self.assertIsNone(initial_item["last_read_seq"])

        mark_read_response = await self.client.post(
            "/v1/conversations/mark_read",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"conv_id": "conv_reads"},
        )
        self.assertEqual(mark_read_response.status, 200)
        mark_read_body = await mark_read_response.json()
        self.assertEqual(mark_read_body["status"], "ok")
        self.assertEqual(mark_read_body["conv_id"], "conv_reads")
        self.assertEqual(mark_read_body["last_read_seq"], 2)
        self.assertEqual(mark_read_body["unread_count"], 0)

        await self._send_inbox(
            alice_token,
            conv_id="conv_reads",
            msg_id="m3",
            env="ZW52Mw==",
            ts_ms=3000,
        )
        post_send_list = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        self.assertEqual(post_send_list.status, 200)
        post_send_item = (await post_send_list.json())["items"][0]
        self.assertEqual(post_send_item["last_read_seq"], 2)
        self.assertEqual(post_send_item["unread_count"], 1)

        runtime = self.app[RUNTIME_KEY]
        with runtime.backend.lock:
            runtime.backend.connection.execute(
                "DELETE FROM conv_events WHERE conv_id=? AND seq=?",
                ("conv_reads", 1),
            )
            runtime.backend.connection.execute(
                "UPDATE conversation_reads SET last_read_seq=? WHERE conv_id=? AND user_id=?",
                (0, "conv_reads", "u_alice"),
            )

        clamped_list = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        self.assertEqual(clamped_list.status, 200)
        clamped_item = (await clamped_list.json())["items"][0]
        self.assertEqual(clamped_item["earliest_seq"], 2)
        self.assertEqual(clamped_item["last_read_seq"], 1)
        self.assertEqual(clamped_item["unread_count"], 2)


    async def test_conversation_naming_pinning_and_permissions(self):
        alice_token = await self._session("u_alice", "d_alice")
        bob_token = await self._session("u_bob", "d_bob")
        eve_token = await self._session("u_eve", "d_eve")

        await self._create_room(alice_token, "conv_named_a", ["u_bob"])
        await self._create_room(alice_token, "conv_named_b", ["u_bob"])

        set_title = await self.client.post(
            "/v1/conversations/title",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"conv_id": "conv_named_a", "title": "  Team   Room  "},
        )
        self.assertEqual(set_title.status, 200)
        self.assertEqual((await set_title.json())["title"], "Team Room")

        bob_title = await self.client.post(
            "/v1/conversations/title",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"conv_id": "conv_named_a", "title": "Nope"},
        )
        self.assertEqual(bob_title.status, 403)

        set_label = await self.client.post(
            "/v1/conversations/label",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"conv_id": "conv_named_a", "label": "Private Name"},
        )
        self.assertEqual(set_label.status, 200)

        pin_b = await self.client.post(
            "/v1/conversations/pin",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"conv_id": "conv_named_b", "pinned": True},
        )
        self.assertEqual(pin_b.status, 200)

        bob_list = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(bob_list.status, 200)
        bob_items = (await bob_list.json())["items"]
        self.assertEqual([item["conv_id"] for item in bob_items], ["conv_named_b", "conv_named_a"])
        by_conv = {item["conv_id"]: item for item in bob_items}
        self.assertEqual(by_conv["conv_named_a"]["display_name"], "Private Name")
        self.assertEqual(by_conv["conv_named_a"]["title"], "Team Room")
        self.assertTrue(by_conv["conv_named_b"]["pinned"])
        self.assertGreaterEqual(by_conv["conv_named_b"]["pinned_at_ms"], 1)

        alice_list = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        self.assertEqual(alice_list.status, 200)
        alice_conv_a = next(item for item in (await alice_list.json())["items"] if item["conv_id"] == "conv_named_a")
        self.assertEqual(alice_conv_a["display_name"], "Team Room")

        for path, payload in (
            ("/v1/conversations/title", {"conv_id": "conv_named_a", "title": "x"}),
            ("/v1/conversations/label", {"conv_id": "conv_named_a", "label": "x"}),
            ("/v1/conversations/pin", {"conv_id": "conv_named_a", "pinned": True}),
        ):
            response = await self.client.post(
                path,
                headers={"Authorization": f"Bearer {eve_token}"},
                json=payload,
            )
            self.assertEqual(response.status, 403)

    async def test_conversation_mute_archive_listing_and_permissions(self):
        alice_token = await self._session("u_alice", "d_alice")
        bob_token = await self._session("u_bob", "d_bob")
        eve_token = await self._session("u_eve", "d_eve")

        await self._create_room(alice_token, "conv_room", ["u_bob"])
        dm_response = await self.client.post(
            "/v1/dms/create",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"peer_user_id": "u_bob", "conv_id": "conv_dm"},
        )
        self.assertEqual(dm_response.status, 200)

        initial_list = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(initial_list.status, 200)
        initial_items = (await initial_list.json())["items"]
        self.assertEqual(sorted(item["conv_id"] for item in initial_items), ["conv_dm", "conv_room"])
        for item in initial_items:
            self.assertFalse(item.get("muted"))
            self.assertFalse(item.get("archived"))

        archive_response = await self.client.post(
            "/v1/conversations/archive",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"conv_id": "conv_dm", "archived": True},
        )
        self.assertEqual(archive_response.status, 200)
        self.assertTrue((await archive_response.json())["archived"])

        default_list = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(default_list.status, 200)
        self.assertEqual([item["conv_id"] for item in (await default_list.json())["items"]], ["conv_room"])

        include_archived_list = await self.client.get(
            "/v1/conversations?include_archived=1",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        self.assertEqual(include_archived_list.status, 200)
        by_conv_id = {item["conv_id"]: item for item in (await include_archived_list.json())["items"]}
        self.assertTrue(by_conv_id["conv_dm"]["archived"])
        self.assertFalse(by_conv_id["conv_room"]["archived"])

        mute_response = await self.client.post(
            "/v1/conversations/mute",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"conv_id": "conv_room", "muted": True},
        )
        self.assertEqual(mute_response.status, 200)
        self.assertTrue((await mute_response.json())["muted"])

        refreshed_default = await self.client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        refreshed_item = (await refreshed_default.json())["items"][0]
        self.assertEqual(refreshed_item["conv_id"], "conv_room")
        self.assertTrue(refreshed_item["muted"])
        self.assertFalse(refreshed_item["archived"])

        refreshed_include = await self.client.get(
            "/v1/conversations?include_archived=1",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        refreshed_by_conv = {item["conv_id"]: item for item in (await refreshed_include.json())["items"]}
        self.assertTrue(refreshed_by_conv["conv_room"]["muted"])
        self.assertTrue(refreshed_by_conv["conv_dm"]["archived"])

        for path, payload in (
            ("/v1/conversations/mute", {"conv_id": "conv_room", "muted": True}),
            ("/v1/conversations/archive", {"conv_id": "conv_room", "archived": True}),
            ("/v1/conversations/mute", {"conv_id": "unknown", "muted": True}),
            ("/v1/conversations/archive", {"conv_id": "unknown", "archived": True}),
        ):
            response = await self.client.post(
                path,
                headers={"Authorization": f"Bearer {eve_token}"},
                json=payload,
            )
            self.assertEqual(response.status, 403)
            body = await response.json()
            self.assertEqual(body.get("code"), "forbidden")

if __name__ == "__main__":
    unittest.main()
