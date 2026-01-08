import json
from pathlib import Path
from typing import Iterable
from unittest import mock

from cli_app import gateway_client, mls_poc


class DummyResponse:
    def __init__(self, payload: bytes, lines: Iterable[bytes] | None = None):
        self._payload = payload
        self._lines = list(lines or [])

    def read(self) -> bytes:
        return self._payload

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_session_start_posts_expected_payload_and_headers():
    def fake_urlopen(request):
        assert request.full_url == "https://gw.test/v1/session/start"
        assert request.get_header("Content-Type") == "application/json"
        payload = json.loads(request.data.decode("utf-8"))
        assert payload == {
            "auth_token": "Bearer auth",
            "device_id": "device-1",
            "device_credential": "cred",
        }
        return DummyResponse(b'{"session_token":"st","resume_token":"rt"}')

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        response = gateway_client.session_start(
            "https://gw.test",
            "Bearer auth",
            "device-1",
            "cred",
        )

    assert response == {"session_token": "st", "resume_token": "rt"}


def test_session_resume_posts_expected_payload():
    def fake_urlopen(request):
        assert request.full_url == "https://gw.test/v1/session/resume"
        payload = json.loads(request.data.decode("utf-8"))
        assert payload == {"resume_token": "rt"}
        return DummyResponse(b'{"session_token":"st2","resume_token":"rt2"}')

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        response = gateway_client.session_resume("https://gw.test", "rt")

    assert response == {"session_token": "st2", "resume_token": "rt2"}


def test_inbox_send_and_ack_use_authorization_and_snake_case_keys():
    calls = {"send": None, "ack": None}

    def fake_urlopen(request):
        payload = json.loads(request.data.decode("utf-8"))
        if payload["t"] == "conv.send":
            calls["send"] = payload
            assert request.get_header("Authorization") == "Bearer st"
            return DummyResponse(b'{"status":"ok","seq":7}')
        if payload["t"] == "conv.ack":
            calls["ack"] = payload
            assert request.get_header("Authorization") == "Bearer st"
            return DummyResponse(b'{"status":"ok"}')
        raise AssertionError("Unexpected request payload")

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        send_response = gateway_client.inbox_send(
            "https://gw.test",
            "st",
            "c_123",
            "m_456",
            "envb64",
        )
        ack_response = gateway_client.inbox_ack("https://gw.test", "st", "c_123", 7)

    assert send_response == {"seq": 7}
    assert ack_response == {}
    assert calls["send"] == {
        "v": 1,
        "t": "conv.send",
        "body": {"conv_id": "c_123", "msg_id": "m_456", "env": "envb64"},
    }
    assert calls["ack"] == {"v": 1, "t": "conv.ack", "body": {"conv_id": "c_123", "seq": 7}}


def test_sse_tail_parses_data_lines():
    def fake_urlopen(request):
        assert request.full_url == "https://gw.test/v1/sse?conv_id=c_123&from_seq=9"
        assert request.get_header("Authorization") == "Bearer st"
        return DummyResponse(
            b"",
            [
                b"event: conv.event\n",
                b"data: {\"v\":1,\"t\":\"conv.event\",\"body\":{\"seq\":9}}\n",
                b"\n",
                b"data:{\"v\":1,\"t\":\"conv.event\",\"body\":{\"seq\":10}}\n",
            ],
        )

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        events = list(gateway_client.sse_tail("https://gw.test", "st", "c_123", 9))

    assert events == [
        {"v": 1, "t": "conv.event", "body": {"seq": 9}},
        {"v": 1, "t": "conv.event", "body": {"seq": 10}},
    ]


def test_keypackage_directory_endpoints():
    calls = {"publish": None, "fetch": None, "rotate": None}

    def fake_urlopen(request):
        payload = json.loads(request.data.decode("utf-8"))
        if request.full_url == "https://gw.test/v1/keypackages":
            calls["publish"] = payload
            assert request.get_header("Authorization") == "Bearer st"
            return DummyResponse(b'{"status":"ok"}')
        if request.full_url == "https://gw.test/v1/keypackages/fetch":
            calls["fetch"] = payload
            assert request.get_header("Authorization") == "Bearer st"
            return DummyResponse(b'{"keypackages":["kp1","kp2"]}')
        if request.full_url == "https://gw.test/v1/keypackages/rotate":
            calls["rotate"] = payload
            assert request.get_header("Authorization") == "Bearer st"
            return DummyResponse(b'{"status":"ok"}')
        raise AssertionError("Unexpected request url")

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        publish_response = gateway_client.keypackages_publish(
            "https://gw.test",
            "st",
            "device-1",
            ["kp1"],
        )
        fetch_response = gateway_client.keypackages_fetch(
            "https://gw.test",
            "st",
            "user-1",
            2,
        )
        rotate_response = gateway_client.keypackages_rotate(
            "https://gw.test",
            "st",
            "device-1",
            True,
            ["kp2"],
        )

    assert publish_response == {"status": "ok"}
    assert fetch_response == {"keypackages": ["kp1", "kp2"]}
    assert rotate_response == {"status": "ok"}
    assert calls["publish"] == {"device_id": "device-1", "keypackages": ["kp1"]}
    assert calls["fetch"] == {"user_id": "user-1", "count": 2}
    assert calls["rotate"] == {
        "device_id": "device-1",
        "revoke": True,
        "replacement": ["kp2"],
    }


def test_room_create_posts_expected_payload():
    def fake_urlopen(request):
        assert request.full_url == "https://gw.test/v1/rooms/create"
        assert request.get_header("Authorization") == "Bearer st"
        payload = json.loads(request.data.decode("utf-8"))
        assert payload == {"conv_id": "c_123", "members": ["u_456"]}
        return DummyResponse(b'{"status":"ok"}')

    with mock.patch("urllib.request.urlopen", fake_urlopen):
        response = gateway_client.room_create("https://gw.test", "st", "c_123", ["u_456"])

    assert response == {"status": "ok"}


def test_load_session_uses_explicit_path():
    session_path = Path("session.json")
    with mock.patch("cli_app.mls_poc.gateway_store.load_session") as load_session:
        load_session.return_value = {
            "base_url": "https://gw.test",
            "session_token": "st",
            "resume_token": "rt",
        }
        base_url, session_token = mls_poc._load_session(None, session_path)

    load_session.assert_called_once_with(session_path)
    assert base_url == "https://gw.test"
    assert session_token == "st"
