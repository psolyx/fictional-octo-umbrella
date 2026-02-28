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
        cls.styles_css = read_repo_text("clients", "web", "styles.css")
        cls.dm_ui = read_repo_text("clients", "web", "dm_ui.js")
        cls.social_ui = read_repo_text("clients", "web", "social_ui.js")
        cls.mls_vectors_loader = read_repo_text("clients", "web", "mls_vectors_loader.js")
        cls.identity_js = read_repo_text("clients", "web", "identity.js")

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



    def test_mark_all_read_contract_markers(self):
        self.assertIn('data-test="conv-mark-all-read"', self.index_html)
        self.assertIn('/v1/conversations/mark_all_read', self.gateway_ws_client)

    def test_conversation_filter_contract_markers(self):
        for marker in (
            'data-test="conv-filter-q"',
            'data-test="conv-filter-unread"',
            'data-test="conv-filter-pinned"',
            'data-test="conv-filter-clear"',
            'data-test="conv-filter-status"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.index_html)
        for marker in ("conv_filter_q", "conv_filter_unread", "conv_filter_pinned"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.gateway_ws_client)

    def test_message_lifecycle_markers(self):
        self.assertIn("msg-pending", self.gateway_ws_client)
        self.assertIn("Retry send", self.gateway_ws_client)
        self.assertIn("conv-preview", self.gateway_ws_client)

    def test_rate_limit_retry_after_markers(self):
        self.assertIn("Retry-After", self.gateway_ws_client)
        self.assertIn("retry_after_s", self.gateway_ws_client)

    def test_rooms_panel_contracts(self):
        self.assertIn("Rooms v1", self.gateway_ws_client)
        self.assertIn("/v1/rooms/create", self.gateway_ws_client)
        self.assertIn("/v1/rooms/invite", self.gateway_ws_client)
        self.assertIn("/v1/rooms/remove", self.gateway_ws_client)
        self.assertIn("/v1/rooms/promote", self.gateway_ws_client)
        self.assertIn("/v1/rooms/demote", self.gateway_ws_client)
        self.assertIn("/v1/rooms/ban", self.gateway_ws_client)
        self.assertIn("/v1/rooms/unban", self.gateway_ws_client)
        self.assertIn("/v1/rooms/mute", self.gateway_ws_client)
        self.assertIn("/v1/rooms/unmute", self.gateway_ws_client)
        self.assertIn("/v1/rooms/bans", self.gateway_ws_client)
        self.assertIn("/v1/rooms/mutes", self.gateway_ws_client)
        self.assertIn("/v1/rooms/members", self.gateway_ws_client)
        self.assertIn("Generate room id", self.gateway_ws_client)
        self.assertIn("Refresh roster", self.gateway_ws_client)
        self.assertIn("Refresh bans", self.gateway_ws_client)
        self.assertIn("Refresh mutes", self.gateway_ws_client)
        self.assertIn("Ban", self.gateway_ws_client)
        self.assertIn("Unban", self.gateway_ws_client)
        self.assertIn("Mute", self.gateway_ws_client)
        self.assertIn("Unmute", self.gateway_ws_client)
        self.assertIn("Muted members", self.gateway_ws_client)
        self.assertTrue(
            "rooms_roster_list" in self.gateway_ws_client or "rooms-roster-list" in self.gateway_ws_client
        )
        self.assertIn("rooms-roster-row", self.gateway_ws_client)
        self.assertRegex(
            self.gateway_ws_client,
            r"addEventListener\('conv\.selected'[\s\S]{0,400}rooms_conv_id_input\.value",
        )
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
        self.assertIn("MySpace-style profile", self.index_html)
        for marker in (
            'id="profile_banner"',
            'id="profile_avatar"',
            'id="profile_about"',
            'id="profile_interests"',
            'id="profile_friends"',
            'id="profile_bulletins"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.index_html)
        self.assertIn("/v1/social/profile", self.social_ui)
        self.assertIn("/v1/social/feed", self.social_ui)
        self.assertIn("/v1/dms/create", self.social_ui)
        self.assertIn("/v1/presence/blocklist", self.social_ui)
        self.assertIn("/v1/presence/block", self.social_ui)
        self.assertIn("/v1/presence/unblock", self.social_ui)
        self.assertIn('id="profile_message_btn"', self.index_html)
        self.assertIn('data-test="start-dm"', self.index_html)
        self.assertIn('data-test="block-toggle"', self.index_html)
        self.assertIn("Block", self.social_ui)
        self.assertIn("Unblock", self.social_ui)
        self.assertIn("friends-start-dm", self.social_ui)
        self.assertIn("feed-start-dm", self.social_ui)
        self.assertIn("Add Friend", self.social_ui)
        self.assertIn("Remove Friend", self.social_ui)
        for marker in (
            "Pending publishes",
            "social_publish_queue",
            "publish-queue-row",
            "publish-retry",
            "aria-invalid",
            "field-error",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.social_ui if marker.startswith("publish-") or marker == "social_publish_queue" else self.index_html)

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

    def test_presence_contracts(self):
        for marker in (
            '/v1/presence/lease',
            '/v1/presence/renew',
            '/v1/presence/watch',
            '/v1/presence/status',
            'presence.update',
            'data-test="presence-indicator"',
            'Presence enabled',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.gateway_ws_client if marker != 'Presence enabled' else self.index_html)

    def test_account_session_contracts(self):
        self.assertIn('data-test="session-list"', self.index_html)
        self.assertIn('session-client-label', self.identity_js)
        self.assertIn('session-created', self.identity_js)
        self.assertIn('session-last-seen', self.identity_js)
        self.assertIn('label', self.index_html)
        self.assertIn('created', self.index_html)
        self.assertIn('last seen', self.index_html)
        self.assertIn('/v1/session/list', self.identity_js)
        self.assertIn('client_label', self.identity_js)
        self.assertIn('created_at_ms', self.identity_js)
        self.assertIn('last_seen_at_ms', self.identity_js)
        self.assertIn("toISOString", self.identity_js)
        self.assertIn('data-test="session-expired-banner"', self.index_html)
        self.assertIn('data-test="session-expired-reauth"', self.index_html)
        self.assertIn("gateway.session.expired", self.gateway_ws_client)
        self.assertIn("session_expired_banner", self.gateway_ws_client)
        self.assertIn('/v1/session/revoke', self.identity_js)

    def test_rate_limited_marker_contract(self):
        self.assertIn("rate_limited", self.social_ui)
        self.assertIn("rate_limited", self.gateway_ws_client)


    def test_replay_window_error_contracts(self):
        self.assertIn("replay_window_exceeded", self.gateway_ws_client)
        self.assertIn("earliest_seq", self.gateway_ws_client)
        self.assertIn("latest_seq", self.gateway_ws_client)
        self.assertIn("requested_from_seq", self.gateway_ws_client)
        self.assertIn("parse_replay_window_details", self.gateway_ws_client)
        self.assertIn("replay_window_resubscribe_btn", self.gateway_ws_client)
        self.assertIn("client.subscribe(replay_window_conv_id, replay_window_earliest_seq)", self.gateway_ws_client)


    def test_conversations_discovery_contract(self):
        self.assertIn('legend>Conversations<', self.index_html)
        self.assertIn('/v1/conversations', self.gateway_ws_client)
        self.assertIn('/v1/conversations/mark_read', self.gateway_ws_client)
        self.assertIn('/v1/conversations/title', self.gateway_ws_client)
        self.assertIn('/v1/conversations/label', self.gateway_ws_client)
        self.assertIn('/v1/conversations/pin', self.gateway_ws_client)
        self.assertIn('/v1/conversations/mute', self.gateway_ws_client)
        self.assertIn('/v1/conversations/archive', self.gateway_ws_client)
        self.assertIn('include_archived=1', self.gateway_ws_client)
        self.assertIn("conv_id_input.value = item.conv_id", self.gateway_ws_client)
        self.assertIn("unread_count", self.gateway_ws_client)
        self.assertIn("mark_read", self.gateway_ws_client)
        self.assertIn("pruned", self.gateway_ws_client)
        self.assertIn("from_seq_input.value = String(desired_from_seq)", self.gateway_ws_client)
        self.assertIn("subscribe_btn.click()", self.gateway_ws_client)
        self.assertIn("Conversation label", self.index_html)
        self.assertIn("Pinned", self.index_html)
        self.assertIn("Show archived", self.index_html)
        self.assertIn("Mute", self.index_html)
        self.assertIn("Archive", self.index_html)
        self.assertIn("Room title", self.index_html)

    def test_replay_window_ui_marker(self):
        self.assertIn("History pruned", self.index_html)
        self.assertIn("replay_window_banner", self.index_html)
        self.assertIn("replay_window_resubscribe_btn", self.index_html)
        self.assertIn('id="replay_window_banner" role="status"', self.index_html)


    def test_web_secret_redaction_contracts(self):
        self.assertIn("const redact_object =", self.gateway_ws_client)
        self.assertIn("const redact_url =", self.gateway_ws_client)
        self.assertIn("[REDACTED]", self.gateway_ws_client)
        self.assertRegex(
            self.gateway_ws_client,
            r"received \${message\.t \|\| 'unknown'}: \${JSON\.stringify\(redact_object\(body\)\)}",
        )
        self.assertIn("connecting to ${redact_url(url)}", self.gateway_ws_client)

    def test_accessibility_keyboard_contract_markers(self):
        self.assertIn(":focus-visible", self.styles_css)
        self.assertIn("sr-only", self.styles_css)
        self.assertIn('aria-live="polite"', self.index_html)
        self.assertIn("aria-selected", self.gateway_ws_client)
        self.assertIn("tabindex", self.gateway_ws_client)
        self.assertIn('retry_btn.type = \'button\'', self.gateway_ws_client)
    def test_serving_path_regressions(self):
        self.assertNotIn("/clients/web/", self.index_html)
        self.assertIn("open http://localhost:8000/index.html", self.readme)
        self.assertIn("open http://localhost:8000/clients/web/index.html", self.readme)
        self.assertIn("Option A", self.readme)
        self.assertIn("Option B", self.readme)
        self.assertIn("404 for `/clients/web/...`", self.readme)


    def test_account_section_contracts(self):
        self.assertIn('legend>Account<', self.index_html)
        for marker in (
            'Generate identity',
            'Import identity JSON',
            'Export identity JSON',
            'Logout',
            'Logout all devices',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.index_html)


    def test_session_logout_endpoint_contracts(self):
        self.assertIn('/v1/session/logout', self.gateway_ws_client)
        self.assertIn('/v1/session/logout_all', self.gateway_ws_client)

    def test_social_publish_uses_identity_signing_contract(self):
        self.assertNotIn('sig_b64 is required', self.social_ui)
        self.assertIn("import { read_identity } from './identity.js';", self.social_ui)
        self.assertIn("import { sign_social_event } from './social_sign.js';", self.social_ui)

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
