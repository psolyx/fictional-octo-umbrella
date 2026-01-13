import base64
import hashlib
import json
import time
from typing import Any, Dict, Iterable, List, Optional

from cli_app import gateway_client


def _decode_env_bytes(env_b64: str) -> bytes:
    padding = "=" * (-len(env_b64) % 4)
    return base64.urlsafe_b64decode(env_b64 + padding)


def decode_env_kind(env_b64: str) -> Optional[int]:
    if not isinstance(env_b64, str):
        return None
    try:
        env_bytes = _decode_env_bytes(env_b64)
    except Exception:
        return None
    if not env_bytes:
        return None
    return env_bytes[0]


def compute_msg_id_hex(env_b64: str) -> str:
    env_bytes = _decode_env_bytes(env_b64)
    return hashlib.sha256(env_bytes).hexdigest()


def canonicalize_transcript(
    conv_id: str,
    from_seq: int,
    next_seq: Optional[int],
    events: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    canonical_events: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        seq = event.get("seq")
        env = event.get("env")
        msg_id = event.get("msg_id")
        if not isinstance(seq, int) or not isinstance(env, str):
            continue
        if not isinstance(msg_id, str):
            msg_id = None
        canonical_events.append({"seq": seq, "msg_id": msg_id, "env": env})
    canonical_events.sort(key=lambda entry: entry["seq"])
    return {
        "schema_version": 1,
        "conv_id": conv_id,
        "from_seq": from_seq,
        "next_seq": next_seq,
        "events": canonical_events,
    }


def compute_digest_sha256_b64(canonical_payload: Dict[str, Any]) -> str:
    canonical_json = json.dumps(canonical_payload, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def capture_sse_transcript(
    base_url: str,
    session_token: str,
    conv_id: str,
    *,
    from_seq: int = 1,
    timeout_s: float = 15.0,
    max_events: int = 50,
    expected_app_msg_id_hex: Optional[str] = None,
) -> List[Dict[str, Any]]:
    events_by_seq: Dict[int, Dict[str, Any]] = {}
    seen_welcome = False
    seen_commit = False
    seen_app = False
    matched_app_msg = False
    start = time.monotonic()

    for event in gateway_client.sse_tail(
        base_url,
        session_token,
        conv_id,
        from_seq,
        max_events=max_events,
        idle_timeout_s=timeout_s,
    ):
        if time.monotonic() - start > timeout_s:
            break
        if not isinstance(event, dict) or event.get("t") != "conv.event":
            continue
        body = event.get("body", {})
        if not isinstance(body, dict):
            continue
        seq = body.get("seq")
        env = body.get("env")
        msg_id = body.get("msg_id") if isinstance(body.get("msg_id"), str) else None
        if not isinstance(seq, int) or not isinstance(env, str):
            continue
        events_by_seq.setdefault(seq, {"seq": seq, "msg_id": msg_id, "env": env})
        kind = decode_env_kind(env)
        if kind == 0x01:
            seen_welcome = True
        elif kind == 0x02:
            seen_commit = True
        elif kind == 0x03:
            seen_app = True
            if expected_app_msg_id_hex is not None:
                if msg_id is None:
                    raise RuntimeError(
                        "Replay app envelope missing msg_id; cannot validate deterministic msg_id."
                    )
                if msg_id == expected_app_msg_id_hex:
                    matched_app_msg = True
        if seen_welcome and seen_commit and (
            matched_app_msg or (expected_app_msg_id_hex is None and seen_app)
        ):
            break

    if not seen_welcome:
        raise RuntimeError("Replay did not include a welcome (kind=1) envelope before timeout.")
    if not seen_commit:
        raise RuntimeError("Replay did not include a commit (kind=2) envelope before timeout.")
    if not seen_app:
        raise RuntimeError("Replay did not include an app (kind=3) envelope before timeout.")
    if expected_app_msg_id_hex is not None and not matched_app_msg:
        raise RuntimeError(
            "Replay did not include app envelope with expected msg_id; verify the send or increase timeout."
        )

    return list(events_by_seq.values())
