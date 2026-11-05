import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import design_review as review


class ParallelReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.api = self.root / "api.py"
        self.ui = self.root / "ui.ts"
        self.api.write_text("original backend")
        self.ui.write_text("original frontend")
        (self.root / "check.py").write_text(
            """print('{"passed":false,"checks":[{"id":"api","passed":false,"detail":"wrong value"}]}')"""
        )
        (self.root / "contract.json").write_text(json.dumps({
            "editable_files": ["api.py", "ui.ts"], "inputs": [], "checker": [sys.executable, "check.py"]
        }))
        (self.root / "proposal.json").write_text(json.dumps({
            "summary": "Fix backend", "issues": [], "questions": [],
            "change_files": ["api.py"], "verification_plan": ["check"]
        }))
        review.inspect(self.root, "contract.json", "state.json")
        review.propose(self.root, "state.json", "proposal.json")
        review.decide(self.root, "state.json", "approve", "test", "simulated")
        review.begin(self.root, "state.json")
        self.api.write_text("backend edit")

    def test_parallel_frontend_edit_survives_conflict(self):
        self.ui.write_text("parallel edit")
        result = review.verify(self.root, "state.json")
        self.assertEqual(result["phase"], "conflict")
        self.assertIn("ui.ts", result["verification"]["error"])
        self.assertEqual(self.ui.read_text(), "parallel edit")
        self.assertEqual(self.api.read_text(), "backend edit")

    def test_checker_failure_restores_only_approved_file(self):
        before = self.ui.stat()
        result = review.verify(self.root, "state.json")
        self.assertEqual(result["phase"], "rolled_back")
        self.assertEqual(self.api.read_text(), "original backend")
        self.assertEqual(self.ui.stat().st_ino, before.st_ino)
