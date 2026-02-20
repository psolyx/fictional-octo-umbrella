from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[2]
DOC_PATH = ROOT_DIR / "gateway" / "docs" / "presence_privacy_review.md"


class PresencePrivacyReviewDocTests(unittest.TestCase):
    def test_presence_privacy_review_doc_exists_and_has_required_anchors(self) -> None:
        self.assertTrue(DOC_PATH.exists(), "presence privacy review doc is missing")
        text = DOC_PATH.read_text(encoding="utf-8").lower()
        for anchor in ("contacts-only", "watchlist cap", "rate limit", "invisible"):
            self.assertIn(anchor, text)


if __name__ == "__main__":
    unittest.main()
