import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cli_app import mls_poc


def test_dm_send_uses_deterministic_msg_id():
    env_bytes = b"\x03cipher"
    env_b64 = base64.b64encode(env_bytes).decode("utf-8")
    expected_msg_id = hashlib.sha256(env_bytes).hexdigest()

    args = SimpleNamespace(
        conv_id="c_1",
        state_dir="state",
        plaintext="hello",
        base_url=None,
        profile_paths=SimpleNamespace(
            session_path=Path("session.json"),
            cursors_path=Path("cursors.json"),
            identity_path=Path("identity.json"),
        ),
    )

    with mock.patch("cli_app.mls_poc._load_session", return_value=("https://gw", "st")) as load_session:
        with mock.patch("cli_app.mls_poc._run_harness_capture", return_value="ciphertext\n"):
            with mock.patch("cli_app.mls_poc.dm_envelope.pack", return_value=env_b64):
                with mock.patch("cli_app.mls_poc.gateway_client.inbox_send") as inbox_send:
                    inbox_send.return_value = {"seq": 1}
                    mls_poc.handle_gw_dm_send(args)

    inbox_send.assert_called_once()
    load_session.assert_called_once_with(None, args.profile_paths.session_path)
    assert inbox_send.call_args[0][3] == expected_msg_id


def test_dm_init_send_hashes_each_envelope():
    welcome_env_bytes = b"\x01welcome"
    commit_env_bytes = b"\x02commit"
    welcome_env_b64 = base64.b64encode(welcome_env_bytes).decode("utf-8")
    commit_env_b64 = base64.b64encode(commit_env_bytes).decode("utf-8")

    args = SimpleNamespace(
        conv_id="c_2",
        state_dir="state",
        peer_kp_b64="kp",
        group_id="group",
        seed=7,
        base_url=None,
        profile_paths=SimpleNamespace(
            session_path=Path("session.json"),
            cursors_path=Path("cursors.json"),
            identity_path=Path("identity.json"),
        ),
    )

    harness_output = '{"welcome":"welcome-b64","commit":"commit-b64"}\n'

    def pack_side_effect(kind, _payload):
        if kind == 0x01:
            return welcome_env_b64
        if kind == 0x02:
            return commit_env_b64
        raise AssertionError("unexpected kind")

    with mock.patch("cli_app.mls_poc._load_session", return_value=("https://gw", "st")) as load_session:
        with mock.patch("cli_app.mls_poc._run_harness_capture", return_value=harness_output):
            with mock.patch("cli_app.mls_poc.dm_envelope.pack", side_effect=pack_side_effect):
                with mock.patch("cli_app.mls_poc.gateway_client.inbox_send") as inbox_send:
                    inbox_send.side_effect = [{"seq": 1}, {"seq": 2}]
                    mls_poc.handle_gw_dm_init_send(args)

    load_session.assert_called_once_with(None, args.profile_paths.session_path)
    expected_welcome = hashlib.sha256(welcome_env_bytes).hexdigest()
    expected_commit = hashlib.sha256(commit_env_bytes).hexdigest()
    assert inbox_send.call_args_list[0][0][3] == expected_welcome
    assert inbox_send.call_args_list[1][0][3] == expected_commit


def test_dm_tail_routes_and_acks(monkeypatch):
    events = [
        {"body": {"seq": 5, "env": "env1"}},
        {"body": {"seq": 6, "env": "env2"}},
        {"body": {"seq": 7, "env": "env3"}},
    ]

    session_path = Path("session.json")
    cursors_path = Path("cursors.json")
    def fake_load_session(_base, path):
        assert path == session_path
        return "https://gw", "st"

    monkeypatch.setattr("cli_app.mls_poc._load_session", fake_load_session)
    monkeypatch.setattr("cli_app.mls_poc.gateway_client.sse_tail", lambda *_args, **_kwargs: iter(events))

    unpack_results = [(0x01, "welcome"), (0x02, "commit"), (0x03, "ciphertext")]
    monkeypatch.setattr("cli_app.mls_poc.dm_envelope.unpack", lambda _env: unpack_results.pop(0))

    harness_calls = []

    def fake_harness(subcommand, extra_args):
        harness_calls.append((subcommand, extra_args))
        if subcommand == "dm-decrypt":
            return "plaintext\n"
        return ""

    monkeypatch.setattr("cli_app.mls_poc._run_harness_capture", fake_harness)

    acked = []
    monkeypatch.setattr(
        "cli_app.mls_poc.gateway_client.inbox_ack",
        lambda _base, _token, _conv, seq: acked.append(seq),
    )

    update_calls = []
    monkeypatch.setattr(
        "cli_app.mls_poc.gateway_store.get_next_seq",
        lambda _conv, path: 5 if path == cursors_path else 0,
    )
    monkeypatch.setattr(
        "cli_app.mls_poc.gateway_store.update_next_seq",
        lambda _conv, seq, path: update_calls.append((seq, path)),
    )

    args = SimpleNamespace(
        conv_id="c_3",
        state_dir="state",
        from_seq=None,
        ack=True,
        base_url=None,
        profile_paths=SimpleNamespace(
            session_path=session_path,
            cursors_path=cursors_path,
            identity_path=Path("identity.json"),
        ),
    )
    mls_poc.handle_gw_dm_tail(args)

    assert harness_calls[0][0] == "dm-join"
    assert harness_calls[1][0] == "dm-commit-apply"
    assert harness_calls[2][0] == "dm-decrypt"
    assert acked == [5, 6, 7]
    assert update_calls == [(5, cursors_path), (6, cursors_path), (7, cursors_path)]
