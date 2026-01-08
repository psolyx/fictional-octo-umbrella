"""Minimal stdlib gateway client for the CLI."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterator, Optional


def _build_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _post_json(url: str, payload: Dict[str, object], headers: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def session_start(
    base_url: str,
    auth_token: str,
    device_id: str,
    device_credential: Optional[str] = None,
) -> Dict[str, str]:
    payload = {"auth_token": auth_token, "device_id": device_id}
    if device_credential is not None:
        payload["device_credential"] = device_credential
    response = _post_json(_build_url(base_url, "/v1/session/start"), payload)
    return {
        "session_token": str(response["session_token"]),
        "resume_token": str(response["resume_token"]),
    }


def session_resume(base_url: str, resume_token: str) -> Dict[str, str]:
    payload = {"resume_token": resume_token}
    response = _post_json(_build_url(base_url, "/v1/session/resume"), payload)
    return {
        "session_token": str(response["session_token"]),
        "resume_token": str(response["resume_token"]),
    }


def inbox_send(
    base_url: str,
    session_token: str,
    conv_id: str,
    msg_id: str,
    env_b64: str,
    ts: Optional[int] = None,
) -> Dict[str, int]:
    body: Dict[str, object] = {"conv_id": conv_id, "msg_id": msg_id, "env": env_b64}
    payload: Dict[str, object] = {"v": 1, "t": "conv.send", "body": body}
    if ts is not None:
        payload["ts"] = ts
    response = _post_json(
        _build_url(base_url, "/v1/inbox"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )
    return {"seq": int(response["seq"])}


def keypackages_publish(
    base_url: str,
    session_token: str,
    device_id: str,
    keypackages: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"device_id": device_id, "keypackages": keypackages}
    return _post_json(
        _build_url(base_url, "/v1/keypackages"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def keypackages_fetch(
    base_url: str,
    session_token: str,
    user_id: str,
    count: int,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"user_id": user_id, "count": count}
    return _post_json(
        _build_url(base_url, "/v1/keypackages/fetch"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def keypackages_rotate(
    base_url: str,
    session_token: str,
    device_id: str,
    revoke: bool,
    replacement: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "device_id": device_id,
        "revoke": revoke,
        "replacement": replacement,
    }
    return _post_json(
        _build_url(base_url, "/v1/keypackages/rotate"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def room_create(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/create"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def inbox_ack(base_url: str, session_token: str, conv_id: str, seq: int) -> Dict[str, object]:
    payload = {"v": 1, "t": "conv.ack", "body": {"conv_id": conv_id, "seq": seq}}
    _post_json(
        _build_url(base_url, "/v1/inbox"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )
    return {}


def sse_tail(
    base_url: str,
    session_token: str,
    conv_id: str,
    from_seq: int,
    max_events: Optional[int] = None,
    idle_timeout_s: Optional[float] = None,
) -> Iterator[Dict[str, object]]:
    query = urllib.parse.urlencode({"conv_id": conv_id, "from_seq": from_seq})
    url = _build_url(base_url, f"/v1/sse?{query}")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {session_token}"})
    data_lines: list[str] = []
    emitted = 0

    def _flush_event() -> Optional[Dict[str, object]]:
        nonlocal data_lines
        if not data_lines:
            return None
        payload = "\n".join(data_lines)
        data_lines = []
        if not payload:
            return None
        return json.loads(payload)

    try:
        with urllib.request.urlopen(request, timeout=idle_timeout_s) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith(":"):
                    continue
                if not line:
                    event = _flush_event()
                    if event is not None:
                        yield event
                        emitted += 1
                        if max_events is not None and emitted >= max_events:
                            return
                    continue
                if line.startswith("data:"):
                    payload = line[len("data:") :].lstrip()
                    data_lines.append(payload)
        event = _flush_event()
        if event is not None and (max_events is None or emitted < max_events):
            yield event
    except socket.timeout:
        return
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            return
        raise
