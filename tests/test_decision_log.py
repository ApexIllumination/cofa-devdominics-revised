import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from decision_log import append, recall


class JournalTests(unittest.TestCase):
    def test_retry_and_conflict_preserve_original(self):
        with TemporaryDirectory() as td:
            db = Path(td) / "test.sqlite"
            key = (db, "d1", "turn2", "answer", "owner", "DM-2")
            append(*key, {"answer": "allow"})
            append(*key, {"answer": "allow"})
            with self.assertRaises(ValueError):
                append(*key, {"answer": "deny"})
            self.assertEqual([r["detail"] for r in recall(db,"d1")], [{"answer":"allow"}])
            self.assertEqual(recall(db,"d2"), [])

    def test_incomplete_decision_is_not_saved(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                append(Path(td)/"db","d","e","decision","owner","turn",{"choice":"ban"})
