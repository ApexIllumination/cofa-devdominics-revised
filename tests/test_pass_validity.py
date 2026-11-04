import tempfile
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from decision_log import append, check_current


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name)/"db"
        self.save("answer","a",{"answer":"allow","rule_id":"r"})
        self.detail = dict(check_id="check",input_id="input",revision="rev",answers={"r":"a"},
                           expected="ok",actual="ok",status="pass",runs=1)

    def save(self,kind,event,detail):
        append(self.db,"d",event,kind,"actor","source",detail)

    def state(self, rev="rev", rules=None):
        return check_current(self.db,"d","check","input",rev,rules or ["r"])["status"]

    def test_code_or_required_rules_changed(self):
        self.save("verification","v",self.detail)
        self.assertEqual(self.state(),"current_pass")
        self.assertEqual(self.state("rev2"),"stale")
        self.assertEqual(self.state(rules=["r","new"]),"stale")
        self.save("answer","b",{"answer":"deny","rule_id":"r"})
        self.assertEqual(self.state(),"stale")
        self.save("verification","v2",dict(self.detail,answers={"r":"b"},expected="no",status="fail"))
        self.assertEqual(self.state(),"failed")

    def test_old_and_ambiguous_rows(self):
        self.save("verification","old",{k:self.detail[k] for k in ("input_id","expected","actual","status")})
        self.assertEqual(self.state(),"unbound")
        self.save("verification","v",self.detail)
        self.save("answer","unknown-scope",{"answer":"changed"})
        self.assertEqual(self.state(),"unbound")

    def test_incomplete_evidence_never_authorizes_reuse(self):
        for change in (dict(runs=0),dict(actual="no"),dict(answers={"r":"missing"})):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.save("verification","v",dict(self.detail,**change))
        self.assertEqual(self.state(),"not_run")
