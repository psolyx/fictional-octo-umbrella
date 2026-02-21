import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
WEB_ROOT = REPO_ROOT / "clients" / "web"
WEB_TEXT_EXTENSIONS = {".html", ".js", ".md", ".css"}
ALLOWLISTED_API_PREFIXES = ("/v1/", "/v1?", "/v1")
README_ALLOWED_CLIENTS_WEB_SNIPPETS = (
    "open http://localhost:8000/clients/web/index.html",
    "404 for `/clients/web/...`",
)
HTML_ASSET_ATTR_RE = re.compile(
    r"<(?:script|img|link)\b[^>]*(?:src|href)=[\"']([^\"']+)[\"']",
    flags=re.IGNORECASE,
)
JS_ENDPOINT_RE = re.compile(
    r"\bfetch\(\s*[\"'](?P<fetch>[^\"']+)"
    r"|\bnew\s+WebSocket\(\s*[\"'](?P<ws>[^\"']+)"
    r"|\bnew\s+EventSource\(\s*[\"'](?P<sse>[^\"']+)"
)


def read_repo_text(*parts):
    path = REPO_ROOT.joinpath(*parts)
    return path.read_text(encoding="utf-8")


def iter_web_text_files():
    for path in WEB_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in WEB_TEXT_EXTENSIONS:
            continue
        yield path


def read_web_text(path):
    return path.read_text(encoding="utf-8")


def slice_after(text, marker, span=600):
    index = text.find(marker)
    if index == -1:
        return ""
    return text[index : index + span]


def is_disallowed_absolute_path(url):
    return url.startswith("/") and not url.startswith(ALLOWLISTED_API_PREFIXES)


def strip_allowed_snippets(contents, snippets):
    remainder = contents
    for snippet in snippets:
        remainder = remainder.replace(snippet, "")
    return remainder


def collect_absolute_html_asset_paths(contents):
    return [
        match.group(1)
        for match in HTML_ASSET_ATTR_RE.finditer(contents)
        if is_disallowed_absolute_path(match.group(1).strip())
    ]


def collect_disallowed_js_endpoints(contents):
    disallowed = []
    for match in JS_ENDPOINT_RE.finditer(contents):
        for key in ("fetch", "ws", "sse"):
            url = match.group(key)
            if not url:
                continue
            if is_disallowed_absolute_path(url.strip()):
                disallowed.append(url.strip())
    return disallowed


def assert_detail_keys(test_case, window, keys):
    for key in keys:
        pattern = rf"\b{re.escape(key)}\b(?=\s*(?:,|:|}}))"
        test_case.assertRegex(window, pattern)


class TestWebUiContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index_html = read_repo_text("clients", "web", "index.html")
        cls.readme = read_repo_text("clients", "web", "README.md")
        cls.gateway_ws_client = read_repo_text("clients", "web", "gateway_ws_client.js")
        cls.dm_ui = read_repo_text("clients", "web", "dm_ui.js")
        cls.social_ui = read_repo_text("clients", "web", "social_ui.js")
        cls.mls_vectors_loader = read_repo_text("clients", "web", "mls_vectors_loader.js")

    def test_custom_event_contracts_gateway(self):
        marker = "CustomEvent('conv.event.received'"
        self.assertIn(marker, self.gateway_ws_client)
        window = slice_after(self.gateway_ws_client, marker)
        assert_detail_keys(self, window, ("conv_id", "seq", "msg_id", "env"))

        marker = "CustomEvent('conv.selected'"
        self.assertIn(marker, self.gateway_ws_client)
        window = slice_after(self.gateway_ws_client, marker)
        assert_detail_keys(self, window, ("conv_id",))

        marker = "CustomEvent('gateway.session.ready'"
        self.assertIn(marker, self.gateway_ws_client)
        window = slice_after(self.gateway_ws_client, marker)
        assert_detail_keys(self, window, ("session_token", "user_id", "http_base_url"))

        self.assertIn("addEventListener('gateway.send_env'", self.gateway_ws_client)

    def test_rooms_panel_contracts(self):
        self.assertIn("Rooms v1", self.gateway_ws_client)
        self.assertIn("/v1/rooms/create", self.gateway_ws_client)
        self.assertIn("/v1/rooms/invite", self.gateway_ws_client)
        self.assertIn("/v1/rooms/remove", self.gateway_ws_client)
        self.assertRegex(
            self.gateway_ws_client,
            r"Authorization[\s\S]{0,160}Bearer[\s\S]{0,160}session_token",
        )

    def test_custom_event_contracts_dm_ui(self):
        marker = "CustomEvent('dm.outbox.updated'"
        self.assertIn(marker, self.dm_ui)
        window = slice_after(self.dm_ui, marker)
        assert_detail_keys(
            self,
            window,
            ("welcome_env_b64", "commit_env_b64", "app_env_b64"),
        )

        self.assertIn("addEventListener('conv.selected'", self.dm_ui)
        self.assertIn("addEventListener('conv.event.received'", self.dm_ui)
        self.assertIn("Auto-apply commit after echo", self.dm_ui)
        self.assertIn("Auto-decrypt app env on ingest", self.dm_ui)
        self.assertIn("Auto-join on welcome ingest", self.dm_ui)
        self.assertIn("Run next step", self.dm_ui)
        self.assertIn("auto_apply_commit_after_echo", self.dm_ui)
        self.assertIn("auto_decrypt_app_env", self.dm_ui)
        self.assertIn("auto_join_on_welcome", self.dm_ui)
        self.assertIn("bound to conv_id", self.dm_ui)
        self.assertIn("/v1/keypackages/fetch", self.dm_ui)
        self.assertIn("/v1/keypackages", self.dm_ui)

    def test_social_panel_contracts(self):
        self.assertIn("Social (Polycentric)", self.index_html)
        self.assertIn("social_ui.js", self.index_html)
        self.assertIn("/v1/social/events", self.social_ui)
        marker = "CustomEvent('social.peer.selected'"
        self.assertIn(marker, self.social_ui)
        window = slice_after(self.social_ui, marker)
        assert_detail_keys(self, window, ("user_id",))
        self.assertIn("addEventListener('social.peer.selected'", self.dm_ui)

    def test_dm_echo_before_apply_gate(self):
        marker = "addEventListener('dm.commit.echoed'"
        self.assertIn(marker, self.dm_ui)
        window = slice_after(self.dm_ui, marker, span=800)
        self.assertIn("last_local_commit_env_b64", window)
        self.assertIn("detail.env_b64", window)
        self.assertRegex(
            window,
            r"detail\.env_b64\s*(?:===|!==)\s*last_local_commit_env_b64",
        )
        self.assertIn("set_commit_echo_state('received'", window)


    def test_replay_window_error_contracts(self):
        self.assertIn("replay_window_exceeded", self.gateway_ws_client)
        self.assertIn("earliest_seq", self.gateway_ws_client)
        self.assertIn("latest_seq", self.gateway_ws_client)
        self.assertIn("requested_from_seq", self.gateway_ws_client)
        self.assertIn("parse_replay_window_details", self.gateway_ws_client)
        self.assertIn("replay_window_resubscribe_btn", self.gateway_ws_client)
        self.assertIn("client.subscribe(replay_window_conv_id, replay_window_earliest_seq)", self.gateway_ws_client)

    def test_replay_window_ui_marker(self):
        self.assertIn("History pruned", self.index_html)
        self.assertIn("replay_window_banner", self.index_html)
        self.assertIn("replay_window_resubscribe_btn", self.index_html)
    def test_serving_path_regressions(self):
        self.assertNotIn("/clients/web/", self.index_html)
        self.assertIn("open http://localhost:8000/index.html", self.readme)
        self.assertIn("open http://localhost:8000/clients/web/index.html", self.readme)
        self.assertIn("Option A", self.readme)
        self.assertIn("Option B", self.readme)
        self.assertIn("404 for `/clients/web/...`", self.readme)

    def test_web_assets_have_no_absolute_serve_paths(self):
        clients_web_refs = []
        html_absolute_assets = []
        js_absolute_endpoints = []
        for path in iter_web_text_files():
            contents = read_web_text(path)
            if "/clients/web/" in contents:
                if path.name == "README.md":
                    remainder = strip_allowed_snippets(
                        contents, README_ALLOWED_CLIENTS_WEB_SNIPPETS
                    )
                    if "/clients/web/" in remainder:
                        clients_web_refs.append(str(path.relative_to(REPO_ROOT)))
                else:
                    clients_web_refs.append(str(path.relative_to(REPO_ROOT)))
            if path.suffix.lower() == ".html":
                for url in collect_absolute_html_asset_paths(contents):
                    html_absolute_assets.append(
                        f"{path.relative_to(REPO_ROOT)}: {url}"
                    )
            if path.suffix.lower() in {".html", ".js"}:
                for url in collect_disallowed_js_endpoints(contents):
                    js_absolute_endpoints.append(
                        f"{path.relative_to(REPO_ROOT)}: {url}"
                    )
        self.assertEqual(
            clients_web_refs,
            [],
            msg="Found hard-coded /clients/web/ references in web assets",
        )
        self.assertEqual(
            html_absolute_assets,
            [],
            msg="HTML assets should not use absolute paths for local files",
        )
        self.assertEqual(
            js_absolute_endpoints,
            [],
            msg="JS fetch/WebSocket/EventSource calls should not use absolute local paths",
        )

    def test_index_html_uses_relative_asset_paths(self):
        script_srcs = re.findall(
            r"<script[^>]+src=[\"']([^\"']+)[\"']",
            self.index_html,
            flags=re.IGNORECASE,
        )
        link_hrefs = re.findall(
            r"<link[^>]+href=[\"']([^\"']+)[\"']",
            self.index_html,
            flags=re.IGNORECASE,
        )
        inline_fetches = re.findall(
            r"fetch\(\s*[\"']([^\"']+)[\"']",
            self.index_html,
        )
        asset_urls = script_srcs + link_hrefs + inline_fetches
        absolute_assets = []
        for url in asset_urls:
            if is_disallowed_absolute_path(url):
                absolute_assets.append(url)
        self.assertEqual(
            absolute_assets,
            [],
            msg="index.html should use relative asset paths; absolute paths are reserved for API calls",
        )

    def test_wasm_vector_path_is_relative(self):
        self.assertIn("vendor/mls_harness.wasm", self.mls_vectors_loader)
        self.assertNotIn("/vendor/mls_harness.wasm", self.mls_vectors_loader)

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
                self.assertNotIn(token, self.social_ui)


if __name__ == "__main__":
    unittest.main()
