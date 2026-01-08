import json
from typing import Iterable
from unittest import mock

from cli_app import gateway_client


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
