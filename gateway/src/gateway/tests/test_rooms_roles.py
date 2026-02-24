import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from gateway.ws_transport import create_app


class RoomsRolesTests(unittest.IsolatedAsyncioTestCase):
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
        return str((await response.json())["session_token"])

    async def _rooms_post(self, token: str, endpoint: str, conv_id: str, members: list[str]):
        return await self.client.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            json={"conv_id": conv_id, "members": members},
        )

    async def _rooms_members(self, token: str | None, conv_id: str):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return await self.client.get(
            "/v1/rooms/members",
            headers=headers,
            params={"conv_id": conv_id},
        )

    async def _dms_create(self, token: str | None, peer_user_id: str, conv_id: str | None = None):
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        payload = {"peer_user_id": peer_user_id}
        if conv_id is not None:
            payload["conv_id"] = conv_id
        return await self.client.post("/v1/dms/create", headers=headers, json=payload)

    async def test_dms_create_requires_auth(self):
        response = await self._dms_create(None, "u_bob")
        self.assertEqual(response.status, 401)

    async def test_dms_create_rejects_self_peer(self):
        alice_token = await self._session("u_alice", "d_alice")
        response = await self._dms_create(alice_token, "u_alice")
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json()).get("code"), "invalid_request")

    async def test_dms_create_generates_conv_id_and_returns_shape(self):
        alice_token = await self._session("u_alice", "d_alice")
        response = await self._dms_create(alice_token, "u_bob")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertIn("status", payload)
        self.assertIn("conv_id", payload)
        self.assertEqual(payload.get("status"), "ok")
        self.assertTrue(str(payload.get("conv_id", "")).startswith("dm_"))

    async def test_dms_create_rejects_invalid_conv_id(self):
        alice_token = await self._session("u_alice", "d_alice")
        response = await self._dms_create(alice_token, "u_bob", conv_id=" bad conv id ")
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json()).get("code"), "invalid_request")

    async def test_promote_demote_changes_member_permissions(self):
        alice_token = await self._session("u_alice", "d_alice")
        bob_token = await self._session("u_bob", "d_bob")

        create_response = await self._rooms_post(alice_token, "/v1/rooms/create", "conv_room", ["u_bob"])
        self.assertEqual(create_response.status, 200)

        forbidden_invite = await self._rooms_post(bob_token, "/v1/rooms/invite", "conv_room", ["u_charlie"])
        self.assertEqual(forbidden_invite.status, 403)
        forbidden_payload = await forbidden_invite.json()
        self.assertEqual(forbidden_payload.get("code"), "forbidden")

        promote_response = await self._rooms_post(alice_token, "/v1/rooms/promote", "conv_room", ["u_bob"])
        self.assertEqual(promote_response.status, 200)

        bob_invite_after_promote = await self._rooms_post(bob_token, "/v1/rooms/invite", "conv_room", ["u_charlie"])
        self.assertEqual(bob_invite_after_promote.status, 200)

        demote_response = await self._rooms_post(alice_token, "/v1/rooms/demote", "conv_room", ["u_bob"])
        self.assertEqual(demote_response.status, 200)

        forbidden_invite_after_demote = await self._rooms_post(bob_token, "/v1/rooms/invite", "conv_room", ["u_dave"])
        self.assertEqual(forbidden_invite_after_demote.status, 403)
        forbidden_after_demote_payload = await forbidden_invite_after_demote.json()
        self.assertEqual(forbidden_after_demote_payload.get("code"), "forbidden")

    async def test_room_members_requires_auth(self):
        response = await self._rooms_members(None, "conv_room")
        self.assertEqual(response.status, 401)

    async def test_room_members_forbidden_for_unknown_or_non_member(self):
        alice_token = await self._session("u_alice", "d_alice")
        bob_token = await self._session("u_bob", "d_bob")
        charlie_token = await self._session("u_charlie", "d_charlie")

        create_response = await self._rooms_post(alice_token, "/v1/rooms/create", "conv_roster", ["u_bob"])
        self.assertEqual(create_response.status, 200)

        not_member_response = await self._rooms_members(charlie_token, "conv_roster")
        self.assertEqual(not_member_response.status, 403)
        self.assertEqual((await not_member_response.json()).get("code"), "forbidden")

        unknown_response = await self._rooms_members(bob_token, "conv_missing")
        self.assertEqual(unknown_response.status, 403)
        self.assertEqual((await unknown_response.json()).get("code"), "forbidden")

    async def test_room_members_returns_sorted_roles_after_promote_and_demote(self):
        owner_token = await self._session("u_owner", "d_owner")
        admin_b_token = await self._session("u_admin_b", "d_admin_b")

        create_response = await self._rooms_post(
            owner_token,
            "/v1/rooms/create",
            "conv_ordered",
            ["u_member_z", "u_admin_b", "u_admin_a", "u_member_a"],
        )
        self.assertEqual(create_response.status, 200)

        promote_response = await self._rooms_post(
            owner_token,
            "/v1/rooms/promote",
            "conv_ordered",
            ["u_admin_b", "u_admin_a"],
        )
        self.assertEqual(promote_response.status, 200)

        demote_response = await self._rooms_post(
            owner_token,
            "/v1/rooms/demote",
            "conv_ordered",
            ["u_admin_b"],
        )
        self.assertEqual(demote_response.status, 200)

        roster_response = await self._rooms_members(admin_b_token, "conv_ordered")
        self.assertEqual(roster_response.status, 200)
        payload = await roster_response.json()
        self.assertEqual(payload.get("conv_id"), "conv_ordered")
        self.assertEqual(
            payload.get("members"),
            [
                {"user_id": "u_owner", "role": "owner"},
                {"user_id": "u_admin_a", "role": "admin"},
                {"user_id": "u_admin_b", "role": "member"},
                {"user_id": "u_member_a", "role": "member"},
                {"user_id": "u_member_z", "role": "member"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
