import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/diagnose_data.py"


class DataDiagnosticTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.dir,
                              text=True, capture_output=True)

    def test_join_keeps_missing_separate_and_traces_exact_multiplicity(self):
        (self.dir / "facts.csv").write_text(
            "\ufeffid,key,n\nA,01,0.1\nA,1,0\nB,,\nC,X,oops\n", encoding="utf-8")
        (self.dir / "ref.json").write_text(
            '[{"code":"01"},{"code":"01"},{"code":1},{"code":null}]')
        run = self.run_cli("facts.csv", "--key", "id", "--reference", "ref.json",
                           "--join-key", "key", "--reference-key", "code", "--sum", "n", "--limit", "1")
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report["input"]["duplicates"], [{"value": "A", "count": 2, "records": [1]}])
        self.assertEqual(report["input"]["columns"]["n"]["zero"]["records"], [2])
        join = report["join"]
        self.assertEqual((join["before_rows"], join["after_rows"]), (4, 5))
        self.assertEqual(join["issues"]["multiple_matches"]["records"],
                         [{"record": 1, "value": "01", "match_count": 2, "reference_records": [1]}])
        self.assertEqual(join["issues"]["unmatched_key"]["count"], 2)
        self.assertEqual(join["issues"]["missing_key"]["records"][0]["record"], 3)
        self.assertEqual((join["sum"]["before"], join["sum"]["after"]), ("0.1", "0.2"))
        self.assertEqual(join["sum"]["excluded"]["invalid_number"]["records"], [4])
        self.assertEqual(join["sum"]["excluded"]["missing_number"]["records"], [3])

    def test_single_json_profiles_sparse_fields_and_does_not_count_false_as_zero(self):
        (self.dir / "input.json").write_text('[{"n":false},{"k":"item"},{"n":0}]')
        result = self.run_cli("input.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        column = json.loads(result.stdout)["input"]["columns"]["n"]
        self.assertEqual(column["zero"]["records"], [3])
        self.assertEqual(column["missing"]["records"], [2])

    def test_rejects_ambiguous_or_malformed_inputs(self):
        for name, content in [("dup.csv", "k,k\n1,2"), ("short.csv", "a,b\n1"),
                              ("dup.json", '[{"k":1,"k":2}]')]:
            with self.subTest(name=name):
                (self.dir / name).write_text(content)
                result = self.run_cli(name)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(result.stdout)
