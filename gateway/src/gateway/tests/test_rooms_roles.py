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


if __name__ == "__main__":
    unittest.main()
