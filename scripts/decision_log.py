"""Append sourced events and recall a single decision. CLI uses only the stdlib."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

FIELDS = {"answer": {"answer"}, "decision": {"choice", "reason", "alternative", "why_rejected"},
          "verification": {"input_id", "expected", "actual", "status"}}


def append(db, decision_id, event_id, kind, actor, source, detail):
    if not all(isinstance(v, str) and v.strip() for v in (decision_id,event_id,kind,actor,source)):
        raise ValueError("decision_id, event_id, kind, actor and source are required")
    fields = set(detail) if isinstance(detail, dict) else set()
    bound = kind == "verification" and fields == FIELDS["verification"] | {"check_id", "revision", "answers", "runs"}
    scoped = kind == "answer" and fields == {"answer", "rule_id"}
    if kind not in FIELDS or not isinstance(detail, dict) or not (bound or scoped or fields == FIELDS[kind]):
        raise ValueError(f"expected detail fields: {FIELDS.get(kind)}")
    if not all(isinstance(v, str) and v.strip() for k,v in detail.items() if not bound or k not in ("answers","runs")):
        raise ValueError("detail values must be nonempty strings; use 'unknown' when unrecorded")
    if kind == "verification" and detail["status"] not in ("pass","fail","pending"):
        raise ValueError("invalid verification status")
    if bound:
        refs = detail["answers"]
        if not isinstance(refs, dict) or not refs or not all(
                isinstance(v, str) and v.strip() for pair in refs.items() for v in pair):
            raise ValueError("answers must map each relevant rule ID to its confirmed answer event ID")
        runs = detail["runs"]
        if type(runs) is not int or runs < 0:
            raise ValueError("runs must be a nonnegative integer")
        if any(detail[k].strip().lower() == "unknown" for k in ("revision","input_id","check_id")):
            raise ValueError("missing check identity")
        if runs == 0 and detail["status"] != "pending":
            raise ValueError("zero executions must be pending")
        if detail["status"] == "pass" and (detail["expected"] != detail["actual"] or
                detail["actual"].strip().lower() == "unknown"):
            raise ValueError("PASS requires equal, known canonical results")
    values = (kind, actor, source, json.dumps(detail, sort_keys=True, ensure_ascii=False))
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS events (decision_id TEXT,event_id TEXT,kind TEXT,"
                     "actor TEXT,source TEXT,detail TEXT,recorded_at TEXT,PRIMARY KEY(decision_id,event_id))")
        if bound:
            for rule, ref in detail["answers"].items():
                answer = conn.execute("SELECT detail FROM events WHERE decision_id=? AND event_id=? AND kind='answer'",
                                      (decision_id,ref)).fetchone()
                if not answer or json.loads(answer[0]).get("rule_id") != rule:
                    raise ValueError("answer reference does not match decision and rule")
        conn.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?) ON CONFLICT(decision_id,event_id) DO NOTHING",
                     (decision_id,event_id,*values,datetime.now(timezone.utc).isoformat()))
        saved = conn.execute("SELECT kind,actor,source,detail FROM events WHERE decision_id=? AND event_id=?",
                             (decision_id,event_id)).fetchone()
        if saved != values:
            raise ValueError("event ID already used with different content")
    return event_id


def recall(db, decision_id):
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+"?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT event_id,kind,actor,source,detail,recorded_at FROM events "
                            "WHERE decision_id=? ORDER BY rowid", (decision_id,)).fetchall()
    return [dict(event_id=i,kind=k,actor=a,source=s,detail=json.loads(d),recorded_at=t)
            for i,k,a,s,d,t in rows]


def check_current(db, decision_id, check_id, input_id, revision, rule_ids):
    """Assess one exact-result check against a single journal snapshot."""
    if not all(isinstance(v, str) and v.strip() and v.strip().lower() != "unknown"
               for v in (decision_id,check_id,input_id,revision)):
        raise ValueError("supply current decision, check, input and revision IDs")
    if not isinstance(rule_ids, list) or not rule_ids or not all(
            isinstance(k, str) and k.strip() for k in rule_ids):
        raise ValueError("supply the current relevant rule IDs")
    events = recall(db, decision_id) if Path(db).is_file() else []
    latest_answers = {}
    check = None
    legacy = False
    unclassified_answer = False
    for event in events:
        d = event["detail"]
        if event["kind"] == "answer" and "rule_id" in d:
            latest_answers[d["rule_id"]] = event["event_id"]
        elif event["kind"] == "answer" and check is not None:
            unclassified_answer = True
        if event["kind"] == "verification" and d["input_id"] == input_id:
            if d.get("check_id") == check_id:
                check = event
                unclassified_answer = False
            elif "check_id" not in d:
                legacy = True
                check = None
    def result(status, reason):
        return dict(status=status, reuse_pass=status=="current_pass", reason=reason,
                    event_id=check["event_id"] if check else None)
    if check is None:
        return result("unbound" if legacy else "not_run", "No bound execution for this check and input")
    d = check["detail"]
    if not d["runs"] or d["status"] == "pending":
        return result("not_run", "No completed result")
    changed = sorted(k for k in set(rule_ids) | set(d["answers"])
                     if k not in rule_ids or k not in d["answers"]
                     or latest_answers.get(k) != d["answers"][k])
    if unclassified_answer:
        return result("unbound", "Later HR answer has no assigned rule; review its scope")
    if changed or d["revision"] != revision:
        return result("stale", "Changed: " + ", ".join(changed + (["implementation/check revision"]
                      if d["revision"] != revision else [])))
    if d["status"] != "pass":
        return result("failed", "Latest completed execution failed")
    return result("current_pass", "Bound result, relevant answers and revision match")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", required=True, type=Path)
    subs = p.add_subparsers(dest="cmd", required=True)
    subs.add_parser("append", help="read one JSON event from stdin")
    subs.add_parser("recall").add_argument("decision_id")
    audit = subs.add_parser("current")
    for key in ("decision_id","check_id","input_id","revision"):
        audit.add_argument(key)
    audit.add_argument("--rule", action="append", required=True, dest="rules")
    args = p.parse_args()
    if args.cmd == "current":
        result = check_current(args.db,args.decision_id,args.check_id,args.input_id,args.revision,args.rules)
    elif args.cmd == "append":
        result = append(args.db, **json.load(sys.stdin))
    else:
        result = recall(args.db,args.decision_id)
    print(json.dumps(result,ensure_ascii=False,indent=2))
