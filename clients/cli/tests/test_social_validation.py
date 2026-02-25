import unittest

from cli_app.social_validate import validate_profile_field


class TestSocialValidation(unittest.TestCase):
    def test_username_rules(self):
        self.assertTrue(validate_profile_field("username", "").startswith("username_invalid_length"))
        self.assertTrue(validate_profile_field("username", "x" * 33).startswith("username_invalid_length"))
        self.assertTrue(validate_profile_field("username", "ok\nno").startswith("username_invalid_newline"))
        self.assertEqual(validate_profile_field("username", "alice"), "")

    def test_url_allowlist(self):
        self.assertEqual(validate_profile_field("avatar", "https://example.com/a.png"), "")
        self.assertEqual(validate_profile_field("banner", "data:image/png;base64,aaaa"), "")
        self.assertTrue(validate_profile_field("avatar", "ftp://example.com").startswith("avatar_invalid_scheme"))

    def test_max_lengths(self):
        self.assertEqual(validate_profile_field("description", "x" * 1024), "")
        self.assertTrue(validate_profile_field("description", "x" * 1025).startswith("description_too_long"))
        self.assertTrue(validate_profile_field("interests", "x" * 1025).startswith("interests_too_long"))


if __name__ == "__main__":
    unittest.main()
