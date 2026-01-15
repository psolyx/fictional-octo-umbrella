import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def read_repo_text(*parts):
    path = REPO_ROOT.joinpath(*parts)
    return path.read_text(encoding="utf-8")


def slice_after(text, marker, span=600):
    index = text.find(marker)
    if index == -1:
        return ""
    return text[index : index + span]


class TestWebUiContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_html = read_repo_text("clients", "web", "index.html")
        cls.readme = read_repo_text("clients", "web", "README.md")
        cls.gateway_ws_client = read_repo_text("clients", "web", "gateway_ws_client.js")
        cls.dm_ui = read_repo_text("clients", "web", "dm_ui.js")

    def test_custom_event_contracts_gateway(self):
        marker = "CustomEvent('conv.event.received'"
        self.assertIn(marker, self.gateway_ws_client)
        window = slice_after(self.gateway_ws_client, marker)
        for key in ("conv_id", "seq", "msg_id", "env"):
            self.assertIn(key, window)

        marker = "CustomEvent('conv.selected'"
        self.assertIn(marker, self.gateway_ws_client)
        window = slice_after(self.gateway_ws_client, marker)
        self.assertIn("conv_id", window)

        self.assertIn("addEventListener('gateway.send_env'", self.gateway_ws_client)

    def test_custom_event_contracts_dm_ui(self):
        marker = "CustomEvent('dm.outbox.updated'"
        self.assertIn(marker, self.dm_ui)
        window = slice_after(self.dm_ui, marker)
        for key in ("welcome_env_b64", "commit_env_b64", "app_env_b64"):
            self.assertIn(key, window)

        self.assertIn("CustomEvent('gateway.send_env'", self.dm_ui)
        self.assertIn("addEventListener('conv.selected'", self.dm_ui)
        self.assertIn("addEventListener('conv.event.received'", self.dm_ui)

    def test_dm_echo_before_apply_gate(self):
        marker = "addEventListener('dm.commit.echoed'"
        self.assertIn(marker, self.dm_ui)
        window = slice_after(self.dm_ui, marker, span=800)
        self.assertIn("last_local_commit_env_b64", window)
        self.assertIn("detail.env_b64", window)
        self.assertIn("detail.env_b64 !== last_local_commit_env_b64", window)
        self.assertIn("set_commit_echo_state('received'", window)

    def test_serving_path_regressions(self):
        self.assertNotIn("/clients/web/", self.index_html)
        self.assertIn("open http://localhost:8000/index.html", self.readme)
        self.assertIn("open http://localhost:8000/clients/web/index.html", self.readme)
        self.assertIn("404 for `/clients/web/...`", self.readme)

    def test_csp_posture(self):
        meta_match = re.search(
            r'http-equiv="Content-Security-Policy" content="([^"]+)"',
            self.index_html,
        )
        self.assertIsNotNone(meta_match)
        csp = meta_match.group(1)
        directives = {}
        for directive in csp.split(";"):
            tokens = directive.strip().split()
            if not tokens:
                continue
            name = tokens[0]
            sources = [token.strip("'\"") for token in tokens[1:]]
            directives[name] = sources

        connect_src = directives.get("connect-src", [])
        self.assertIn("ws:", connect_src)
        self.assertIn("wss:", connect_src)

        script_src = directives.get("script-src", [])
        self.assertIn("wasm-unsafe-eval", script_src)
        self.assertNotIn("unsafe-eval", script_src)

        frame_ancestors = directives.get("frame-ancestors", [])
        self.assertIn("none", frame_ancestors)

    def test_no_camel_protocol_keys_in_web_js(self):
        tokens = [
            ("resume", "Token"),
            ("next", "Seq"),
            ("from", "Seq"),
            ("conv", "Id"),
            ("msg", "Id"),
        ]
        combined = [left + right for left, right in tokens]
        for token in combined:
            with self.subTest(token=token):
                self.assertNotIn(token, self.gateway_ws_client)
                self.assertNotIn(token, self.dm_ui)


if __name__ == "__main__":
    unittest.main()
