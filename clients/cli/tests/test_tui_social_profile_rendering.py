from types import SimpleNamespace
import unittest

from cli_app.tui_app import _build_profile_lines, _format_feed_item


class TestTuiSocialProfileRendering(unittest.TestCase):
    def test_build_profile_lines_prefers_latest_posts_payload_text(self):
        render = SimpleNamespace(
            profile_data={
                "user_id": "alice",
                "friends": ["bob"],
                "latest_posts": [
                    {"ts_ms": 123, "payload": {"text": "hi from payload"}},
                ],
            },
            profile_user_id="alice",
            profile_selected_section="bulletins",
        )

        lines = _build_profile_lines(render)

        self.assertIn("MySpace-style profile", lines)
        self.assertIn("  - 123: hi from payload", lines)

    def test_format_feed_item_extracts_payload_value(self):
        rendered = _format_feed_item(
            {
                "user_id": "alice",
                "ts_ms": 222,
                "payload": {"value": "feed message"},
            }
        )

        self.assertIn("feed message", rendered)


if __name__ == "__main__":
    unittest.main()
