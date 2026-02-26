"""Minimal stdlib gateway client for the CLI."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterator, Optional


class ReplayWindowExceededError(Exception):
    def __init__(self, *, requested_from_seq: int, earliest_seq: int, latest_seq: int):
        self.requested_from_seq = requested_from_seq
        self.earliest_seq = earliest_seq
        self.latest_seq = latest_seq
        super().__init__(
            f"Requested replay from seq {requested_from_seq}, but earliest retained seq is {earliest_seq} (latest={latest_seq})."
        )


def _parse_replay_window_error(http_error: urllib.error.HTTPError) -> ReplayWindowExceededError | None:
    if http_error.code != 410:
        return None
    try:
        raw = http_error.read().decode("utf-8")
        payload = json.loads(raw) if raw else {}
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("code") != "replay_window_exceeded":
        return None
    requested_from_seq = payload.get("requested_from_seq")
    earliest_seq = payload.get("earliest_seq")
    latest_seq = payload.get("latest_seq")
    if not isinstance(requested_from_seq, int):
        requested_from_seq = earliest_seq if isinstance(earliest_seq, int) else 1
    if not isinstance(earliest_seq, int) or not isinstance(latest_seq, int):
        return None
    return ReplayWindowExceededError(
        requested_from_seq=requested_from_seq,
        earliest_seq=earliest_seq,
        latest_seq=latest_seq,
    )


def _emit_reset_event(exc: ReplayWindowExceededError) -> Dict[str, object]:
    return {
        "t": "control.replay_window_reset",
        "body": {
            "requested_from_seq": exc.requested_from_seq,
            "earliest_seq": exc.earliest_seq,
            "latest_seq": exc.latest_seq,
        },
    }


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




def session_logout(base_url: str, session_token: str) -> Dict[str, object]:
    return _post_json(
        _build_url(base_url, "/v1/session/logout"),
        {},
        headers={"Authorization": f"Bearer {session_token}"},
    )


def session_logout_all(base_url: str, session_token: str, include_self: bool) -> Dict[str, object]:
    payload: Dict[str, object] = {"include_self": include_self}
    return _post_json(
        _build_url(base_url, "/v1/session/logout_all"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )

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




def conversations_list(base_url: str, session_token: str, include_archived: bool = False) -> Dict[str, object]:
    path = "/v1/conversations?include_archived=1" if include_archived else "/v1/conversations"
    request = urllib.request.Request(
        _build_url(base_url, path),
        headers={"Authorization": f"Bearer {session_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def conversations_mark_read(
    base_url: str,
    session_token: str,
    conv_id: str,
    to_seq: int | None = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id}
    if isinstance(to_seq, int):
        payload["to_seq"] = to_seq
    return _post_json(
        _build_url(base_url, "/v1/conversations/mark_read"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def conversations_set_title(
    base_url: str,
    session_token: str,
    conv_id: str,
    title: str,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "title": title}
    return _post_json(
        _build_url(base_url, "/v1/conversations/title"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def conversations_set_label(
    base_url: str,
    session_token: str,
    conv_id: str,
    label: str,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "label": label}
    return _post_json(
        _build_url(base_url, "/v1/conversations/label"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def conversations_set_pinned(
    base_url: str,
    session_token: str,
    conv_id: str,
    pinned: bool,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "pinned": pinned}
    return _post_json(
        _build_url(base_url, "/v1/conversations/pin"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def conversations_set_muted(
    base_url: str,
    session_token: str,
    conv_id: str,
    muted: bool,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "muted": muted}
    return _post_json(
        _build_url(base_url, "/v1/conversations/mute"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def conversations_set_archived(
    base_url: str,
    session_token: str,
    conv_id: str,
    archived: bool,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "archived": archived}
    return _post_json(
        _build_url(base_url, "/v1/conversations/archive"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def presence_blocklist(base_url: str, session_token: str) -> list[str]:
    request = urllib.request.Request(
        _build_url(base_url, "/v1/presence/blocklist"),
        headers={"Authorization": f"Bearer {session_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw) if raw else {}
    blocked = payload.get("blocked") if isinstance(payload, dict) else []
    return [entry for entry in blocked if isinstance(entry, str)]


def presence_block(base_url: str, session_token: str, contacts: list[str]) -> Dict[str, object]:
    payload: Dict[str, object] = {"contacts": contacts}
    return _post_json(
        _build_url(base_url, "/v1/presence/block"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def presence_unblock(base_url: str, session_token: str, contacts: list[str]) -> Dict[str, object]:
    payload: Dict[str, object] = {"contacts": contacts}
    return _post_json(
        _build_url(base_url, "/v1/presence/unblock"),
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


def dms_create(
    base_url: str,
    session_token: str,
    peer_user_id: str,
    conv_id: str | None = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {"peer_user_id": peer_user_id}
    if isinstance(conv_id, str) and conv_id:
        payload["conv_id"] = conv_id
    return _post_json(
        _build_url(base_url, "/v1/dms/create"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def room_invite(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/invite"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def room_remove(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/remove"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def room_promote(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/promote"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def room_demote(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/demote"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )




def room_ban(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/ban"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def room_unban(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/unban"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def room_bans(base_url: str, session_token: str, conv_id: str) -> Dict[str, object]:
    request_url = _build_url(base_url, "/v1/rooms/bans") + "?" + urllib.parse.urlencode({"conv_id": conv_id})
    request = urllib.request.Request(
        request_url,
        headers={"Authorization": f"Bearer {session_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}
def rooms_create(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    return room_create(base_url, session_token, conv_id, members)


def rooms_invite(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    return room_invite(base_url, session_token, conv_id, members)


def rooms_remove(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    return room_remove(base_url, session_token, conv_id, members)


def rooms_promote(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    return room_promote(base_url, session_token, conv_id, members)


def rooms_demote(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    return room_demote(base_url, session_token, conv_id, members)


def rooms_ban(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    return room_ban(base_url, session_token, conv_id, members)


def rooms_unban(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    return room_unban(base_url, session_token, conv_id, members)


def rooms_bans(base_url: str, session_token: str, conv_id: str) -> Dict[str, object]:
    return room_bans(base_url, session_token, conv_id)


def rooms_mute(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/mute"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def rooms_unmute(
    base_url: str,
    session_token: str,
    conv_id: str,
    members: list[str],
) -> Dict[str, object]:
    payload: Dict[str, object] = {"conv_id": conv_id, "members": members}
    return _post_json(
        _build_url(base_url, "/v1/rooms/unmute"),
        payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )


def rooms_mutes(base_url: str, session_token: str, conv_id: str) -> Dict[str, object]:
    query = urllib.parse.urlencode({"conv_id": conv_id})
    request = urllib.request.Request(
        _build_url(base_url, f"/v1/rooms/mutes?{query}"),
        headers={"Authorization": f"Bearer {session_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}



def rooms_members(base_url: str, session_token: str, conv_id: str) -> Dict[str, object]:
    query = urllib.parse.urlencode({"conv_id": conv_id})
    request = urllib.request.Request(
        _build_url(base_url, f"/v1/rooms/members?{query}"),
        headers={"Authorization": f"Bearer {session_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}

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
    except urllib.error.HTTPError as exc:
        replay_error = _parse_replay_window_error(exc)
        if replay_error is not None:
            raise replay_error from exc
        raise
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.timeout):
            return
        raise


def sse_tail_resilient(
    base_url: str,
    session_token: str,
    conv_id: str,
    from_seq: int,
    *,
    max_events: Optional[int] = None,
    idle_timeout_s: Optional[float] = None,
    on_reset_callback=None,
    max_resets: int = 1,
    emit_reset_control_event: bool = False,
) -> Iterator[Dict[str, object]]:
    resets = 0
    emitted = 0
    next_from_seq = from_seq
    while True:
        batch_limit = None if max_events is None else max(0, max_events - emitted)
        if batch_limit == 0:
            return
        try:
            for event in sse_tail(
                base_url,
                session_token,
                conv_id,
                next_from_seq,
                max_events=batch_limit,
                idle_timeout_s=idle_timeout_s,
            ):
                yield event
                emitted += 1
                body = event.get("body") if isinstance(event, dict) else None
                if isinstance(body, dict) and isinstance(body.get("seq"), int):
                    next_from_seq = int(body["seq"]) + 1
                if max_events is not None and emitted >= max_events:
                    return
            return
        except ReplayWindowExceededError as exc:
            if resets >= max_resets:
                raise
            resets += 1
            next_from_seq = exc.earliest_seq
            if on_reset_callback is not None:
                on_reset_callback(exc)
            if emit_reset_control_event:
                yield _emit_reset_event(exc)
