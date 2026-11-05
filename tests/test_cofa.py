"""Behavior tests use isolated projects; no real service or model is invoked."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


KIT = Path(__file__).resolve().parents[1]
SCRIPT = KIT / "scripts" / "cofa.py"
spec = importlib.util.spec_from_file_location("cofa", SCRIPT)
cofa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cofa)


APP = '''import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
if "value" not in data:
    print(json.dumps({"status": "needs_input"}))
    sys.exit(2)
result = {"status": "ok", "value": data["value"], "classification": "review" if data.get("exception") else "normal"}
if len(sys.argv) > 2:
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result))
print(json.dumps(result))
'''


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cofa-test-")
        self.root = Path(self.tmp.name) / "project with spaces"
        self.root.mkdir()
        self.write("app.py", APP)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def json(self, relative, data):
        return self.write(relative, json.dumps(data))

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, (result.stdout, result.stderr))
        return json.loads(result.stdout)

    def make_map(self, **changes):
        data = {"schema_version": 1, "purpose": "test pipeline", "entry_points": [{"path": "app.py", "description": "entry"}],
                "flows": [], "watch": {"include": ["**/*.py", "**/*.json"], "exclude": ["out/**", "fixtures/**"]}}
        data.update(changes)
        self.json(".cofa/pipeline-map.json", data)
        return data

    def make_suite(self):
        for name, value in [("normal", {"value": 7}), ("missing", {}), ("critical", {"value": 0, "exception": True})]:
            self.json("fixtures/" + name + ".json", value)
        cases = []
        for name, pointer, expected, code in [("normal", "/value", 7, 0), ("missing", "/status", "needs_input", 2),
                                               ("critical", "/classification", "review", 0)]:
            cases.append({"id": name, "kind": name, "command": ["{python}", "app.py", "fixtures/" + name + ".json"],
                          "inputs": ["fixtures/" + name + ".json"],
                          "expect": {"returncode": code, "stdout": {"json": [{"pointer": pointer, "equals": expected}]}}})
        self.save_cases(cases)
        return cases

    def save_cases(self, cases):
        self.json(".cofa/eval-cases.json", {"schema_version": 1, "cases": cases})

    def report(self):
        return json.loads((self.root / ".cofa/eval-last.json").read_text())


class SourceChecks(ProjectTest):
    def test_uninitialized_check_is_read_only(self):
        self.assertEqual(self.cli("check", expected=2)["status"], "error")
        self.assertFalse((self.root / ".cofa").exists())

    def test_snapshot_and_clean_check(self):
        self.make_map()
        self.assertFalse(self.cli("snapshot")["semantic_consistency_verified"])
        before = (self.root / ".cofa/source-baseline.json").read_bytes()
        result = self.cli("check")
        self.assertEqual(result["status"], "unchanged")
        self.assertFalse(result["semantic_consistency_verified"])
        self.assertEqual(before, (self.root / ".cofa/source-baseline.json").read_bytes())

    def test_added_changed_deleted_and_missing_reference(self):
        self.make_map()
        self.cli("snapshot")
        self.write("helper.py", "answer = 42\n")
        self.write("app.py", APP + "\n# changed\n")
        result = self.cli("check", expected=1)
        self.assertIn("helper.py", result["added"])
        self.assertIn("app.py", result["changed"])
        (self.root / "app.py").unlink()
        result = self.cli("check", expected=1)
        self.assertIn("app.py", result["removed"])
        self.assertIn("app.py", result["missing_references"])

    def test_map_edit_invalidates_baseline(self):
        data = self.make_map()
        self.cli("snapshot")
        data["purpose"] = "changed description"
        self.json(".cofa/pipeline-map.json", data)
        self.assertTrue(self.cli("check", expected=1)["map_changed"])

    def test_reference_outside_globs_is_watched(self):
        self.write("extra/engine.txt", "original")
        self.make_map(entry_points=[{"path": "app.py", "description": "entry"}, {"path": "extra/engine.txt", "description": "reference"}])
        self.cli("snapshot")
        self.write("extra/engine.txt", "modified")
        self.assertIn("extra/engine.txt", self.cli("check", expected=1)["changed"])

    def test_generated_and_metadata_files_do_not_invalidate(self):
        self.make_map()
        self.cli("snapshot")
        self.json("out/generated.json", {"generated": True})
        self.json(".cofa/run.json", {"run": 1})
        self.assertEqual(self.cli("check")["status"], "unchanged")

    def test_missing_reference_refuses_snapshot(self):
        self.make_map(entry_points=[{"path": "absent.py", "description": "absent"}])
        self.cli("snapshot", expected=2)
        self.assertFalse((self.root / ".cofa/source-baseline.json").exists())

    def test_map_does_not_execute_stored_commands(self):
        self.make_map(commands={"run": ["invalid-command-that-must-not-run"]})
        self.assertEqual(self.cli("map")["commands"]["run"], ["invalid-command-that-must-not-run"])

    def test_parent_path_is_rejected(self):
        self.make_map(entry_points=[{"path": "../outside.py", "description": "outside"}])
        self.cli("snapshot", expected=2)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unsupported")
    def test_external_symlink_is_rejected(self):
        target = Path(self.tmp.name) / "outside.py"
        target.write_text("secret = 123")
        (self.root / "link.py").symlink_to(target)
        self.make_map()
        result = self.cli("snapshot", expected=2)
        self.assertNotIn("secret", json.dumps(result))

    @unittest.skipUnless(shutil.which("sh"), "POSIX shell unavailable")
    def test_hook_handles_spaces_and_never_refreshes_baseline(self):
        self.make_map()
        self.cli("snapshot")
        baseline = (self.root / ".cofa/source-baseline.json").read_bytes()
        env = os.environ.copy()
        env["COFA_PYTHON"] = sys.executable
        command = ["sh", str(KIT / "hooks/session-start.sh"), str(self.root)]
        self.assertEqual(subprocess.run(command, env=env, capture_output=True).returncode, 0)
        self.write("app.py", APP + "\n# new session\n")
        self.assertEqual(subprocess.run(command, env=env, capture_output=True).returncode, 1)
        self.assertEqual(baseline, (self.root / ".cofa/source-baseline.json").read_bytes())


class Evaluations(ProjectTest):
    def test_three_business_branches_pass(self):
        self.make_suite()
        result = self.cli("eval")
        self.assertTrue(result["all_cases_executed"])
        self.assertEqual(result["executed_case_count"], 3)
        self.assertIsNone(self.report()["source_before"])

    def test_selected_case_does_not_claim_full_suite(self):
        self.make_suite()
        result = self.cli("eval", "--case", "critical")
        self.assertFalse(result["all_cases_executed"])
        self.assertEqual([c["id"] for c in result["results"]], ["critical"])

    def test_bad_expected_value_fails(self):
        cases = self.make_suite()
        cases[0]["expect"]["stdout"]["json"][0]["equals"] = 999
        self.save_cases(cases)
        result = self.cli("eval", expected=1)
        self.assertEqual(result["results"][0]["status"], "failed")
        self.assertTrue(self.report()["results"][0]["failures"])

    def test_stale_file_cannot_pass(self):
        self.json("out/old.json", {"status": "ok"})
        self.save_cases([{"id": "stale", "command": ["{python}", "-c", "pass"],
                          "expect": {"files": [{"path": "out/old.json", "json": [{"pointer": "/status", "equals": "ok"}]}]}}])
        result = self.cli("eval", expected=1)
        self.assertTrue(any("Stale output" in f for f in result["results"][0]["failures"]))

    def test_fresh_file_passes_even_with_same_contents(self):
        self.make_suite()
        self.json("out/current.json", {"status": "ok", "value": 7, "classification": "normal"})
        self.save_cases([{"id": "fresh", "command": ["{python}", "app.py", "fixtures/normal.json", "out/current.json"],
                          "expect": {"files": [{"path": "out/current.json", "json": [{"pointer": "/value", "equals": 7}]}]}}])
        self.cli("eval")

    def test_null_and_boolean_are_not_zero(self):
        self.make_suite()
        for value in [None, False]:
            with self.subTest(value=value):
                self.json("fixtures/value.json", {"value": value})
                self.save_cases([{"id": "value", "command": ["{python}", "app.py", "fixtures/value.json"],
                                  "expect": {"stdout": {"json": [{"pointer": "/value", "equals": 0}]}}}])
                self.cli("eval", expected=1)

    def test_invalid_json_fails(self):
        self.save_cases([{"id": "text", "command": ["{python}", "-c", "print('not-json')"],
                          "expect": {"stdout": {"json": [{"pointer": "/status", "equals": "ok"}]}}}])
        self.cli("eval", expected=1)

    def test_duplicate_ids_rejected_before_commands_run(self):
        command = ["{python}", "-c", "from pathlib import Path; Path('should-not-run').touch()"]
        case = {"id": "duplicate", "command": command, "expect": {"returncode": 0}}
        self.save_cases([case, case])
        self.cli("eval", expected=2)
        self.assertFalse((self.root / "should-not-run").exists())

    def test_unknown_assertion_and_empty_assertions_are_rejected(self):
        for expect in [{"stdout": {"equalz": "x"}}, {"stdout": {}}, {}]:
            with self.subTest(expect=expect):
                self.save_cases([{"id": "invalid", "command": ["{python}", "-c", "pass"], "expect": expect}])
                self.cli("eval", expected=2)

    def test_timeout_records_failure(self):
        self.save_cases([{"id": "timeout", "command": ["{python}", "-c", "import time; time.sleep(2)"],
                          "timeout_seconds": 0.05, "expect": {"returncode": 0}}])
        self.cli("eval", expected=1)
        self.assertIn("Command timed out", self.report()["results"][0]["failures"])

    def test_missing_command_records_failure(self):
        self.save_cases([{"id": "absent", "command": ["cofa-command-does-not-exist"], "expect": {"returncode": 0}}])
        self.cli("eval", expected=1)
        self.assertIsNone(self.report()["results"][0]["returncode"])

    def test_source_change_during_run_invalidates_evidence(self):
        self.make_map()
        self.save_cases([{"id": "change", "command": ["{python}", "-c", "from pathlib import Path; Path('app.py').write_text('# changed')"],
                          "expect": {"returncode": 0}}])
        result = self.cli("eval", expected=1)
        self.assertTrue(result["source_changed_during_run"])
        self.assertEqual(result["results"][0]["status"], "passed")

    def test_suite_change_during_run_invalidates_evidence(self):
        self.save_cases([{"id": "change-suite", "command": ["{python}", "-c", "from pathlib import Path; p=Path('.cofa/eval-cases.json'); p.write_text(p.read_text()+' ')"],
                          "expect": {"returncode": 0}}])
        self.assertTrue(self.cli("eval", expected=1)["suite_changed_during_run"])

    def test_missing_input_blocks_only_affected_case(self):
        self.save_cases([
            {"id": "missing", "command": ["{python}", "-c", "open('ran', 'w').close()"],
             "inputs": ["absent.csv"], "expect": {"returncode": 0}},
            {"id": "ready", "command": ["{python}", "-c", "pass"], "expect": {"returncode": 0}},
        ])
        report = self.cli("eval", expected=1)
        self.assertFalse((self.root / "ran").exists())
        self.assertEqual(report["executed_case_count"], 1)
        self.assertFalse(report["all_cases_executed"])
        self.assertIn("absent.csv", report["results"][0]["failures"][0])
        self.assertEqual(report["results"][1]["status"], "passed")

    def test_declared_inputs_are_fingerprinted(self):
        self.make_suite()
        self.cli("eval", "--case", "normal")
        case = self.report()["results"][0]
        self.assertTrue(case["inputs_declared"])
        self.assertEqual(len(case["input_fingerprints"]["fixtures/normal.json"]), 64)

    def test_mutating_declared_input_invalidates_case(self):
        self.json("fixtures/value.json", {"value": 1})
        self.save_cases([{"id": "mutate", "command": ["{python}", "-c", "from pathlib import Path; Path('fixtures/value.json').write_text('{}')"],
                          "inputs": ["fixtures/value.json"], "expect": {"returncode": 0}}])
        self.cli("eval", expected=1)
        self.assertTrue(self.report()["results"][0]["inputs_changed_during_case"])

    def test_report_cannot_overwrite_expected_artifact(self):
        self.save_cases([{"id": "artifact", "command": ["{python}", "-c", "pass"],
                          "expect": {"files": [{"path": "out/result.json"}]}}])
        self.cli("eval", "--output", "out/result.json", expected=2)
        self.assertFalse((self.root / "out/result.json").exists())

    def test_outside_report_path_is_rejected(self):
        self.make_suite()
        self.cli("eval", "--output", "../outside.json", expected=2)

    def test_json_pointer_and_value_types(self):
        self.assertEqual(cofa.json_pointer({"a/b": {"~key": ["yes"]}}, "/a~1b/~0key/0"), "yes")
        self.assertFalse(cofa.json_equal({"value": False}, {"value": 0}))
        self.assertFalse(cofa.json_equal(None, 0))
        self.assertTrue(cofa.json_equal([1], [1.0]))


if __name__ == "__main__":
    unittest.main()
