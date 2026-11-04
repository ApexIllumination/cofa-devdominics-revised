import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import next_action


class NextActionTests(unittest.TestCase):
    actions = [{"id": "end", "kind": "stop", "label": "Done"}]

    def test_requires_stop_and_distinct_ids(self):
        for options in ([], self.actions * 2, [dict(self.actions[0], kind="question")]):
            with self.subTest(options=options), self.assertRaises(ValueError):
                next_action.make_prompt({}, options)

    def test_model_cannot_invent_an_action(self):
        def fake_model(args, **kwargs):
            Path(args[args.index("-o") + 1]).write_text(json.dumps(
                {"id": "edit_files", "reason": "not offered"}))
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(subprocess, "run", fake_model), self.assertRaises(ValueError):
            next_action.choose({}, self.actions, "test", guided=False)

    def test_evidence_routing(self):
        actions = self.actions + [
            {"id": kind, "kind": kind, "label": kind, "input_id": "boundary"}
            for kind in ("question", "proposal", "counterexample")]
        observed = {"input_id": "boundary", "value": "ok", "source": "checker"}
        confirmed = dict(observed, source="owner")
        tests = [
            ({}, "counterexample"),
            ({"expected": confirmed}, "counterexample"),
            ({"observed": dict(observed, input_id="ordinary"), "expected": confirmed}, "counterexample"),
            ({"observed": observed, "expected": dict(confirmed, input_id="ordinary")}, "question"),
            ({"observed": observed, "expected": confirmed}, "end"),
            ({"observed": observed, "expected": dict(confirmed, value="infeasible")}, "proposal"),
        ]
        for evidence, expected_id in tests:
            with self.subTest(evidence=evidence):
                result = next_action.choose(
                    {"comparison": dict(input_id="boundary", **evidence)}, actions, "unused")
                self.assertEqual(result["id"], expected_id)

    def test_no_matching_probe_stops_pending(self):
        actions = self.actions + [{"id":"other", "kind":"counterexample", "label":"x", "input_id":"other"}]
        result = next_action.choose({"comparison":{"input_id":"boundary"}}, actions, "unused")
        self.assertEqual(result["id"], "end")
        self.assertIn("Pending", result["reason"])

    def test_missing_source_cannot_authorize_proposal(self):
        with self.assertRaises(ValueError):
            next_action.route_comparison({"input_id":"x", "expected":{"input_id":"x","value":"ok"}},
                                         self.actions)

    def test_model_cannot_skip_a_required_probe(self):
        options = self.actions + [
            {"id": key, "label": key, "kind": kind, "input_id":"boundary"}
            for key, kind in (("first", "counterexample"), ("second", "counterexample"),
                              ("edit", "proposal"))]
        def skip_probe(args, **kwargs):
            Path(args[args.index("-o") + 1]).write_text('{"id":"edit","reason":"skip"}')
            return subprocess.CompletedProcess(args, 0, "", "")
        with patch.object(subprocess, "run", skip_probe), self.assertRaises(ValueError):
            next_action.choose({"comparison":{"input_id":"boundary"}}, options, "test")
