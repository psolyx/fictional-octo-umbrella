from pathlib import Path
import unittest


ROOT_DIR = Path(__file__).resolve().parents[2]
DOC_PATH = ROOT_DIR / "gateway" / "docs" / "retention_and_idempotency.md"


class RetentionAndIdempotencyDocTests(unittest.TestCase):
    def test_retention_and_idempotency_doc_exists_and_has_required_anchors(self) -> None:
        self.assertTrue(DOC_PATH.exists(), "retention/idempotency doc is missing")
        text = DOC_PATH.read_text(encoding="utf-8").lower()
        for anchor in ("no automatic ttl/gc", "operator", "idempotency", "last-resort"):
            self.assertIn(anchor, text)


if __name__ == "__main__":
    unittest.main()
