#!/usr/bin/env python3
"""Portable source-map freshness checks and command-based golden-set evaluation."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


IGNORED_PARTS = {".git", ".cofa", "node_modules", ".venv", "venv", "__pycache__"}
MAP_DEFAULT = ".cofa/pipeline-map.json"
BASELINE_DEFAULT = ".cofa/source-baseline.json"
SUITE_DEFAULT = ".cofa/eval-cases.json"
REPORT_DEFAULT = ".cofa/eval-last.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_path(root, relative):
    require(isinstance(relative, str) and relative, "Expected a relative path")
    rel = Path(relative)
    require(not rel.is_absolute() and ".." not in rel.parts, "Path must stay inside project root")
    path = (root / rel).resolve()
    require(path.is_relative_to(root), "Path resolves outside project root")
    return path


def load_json(path):
    def reject_constant(value):
        raise ValueError("Non-finite JSON number: " + value)
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def digest(path):
    before = path.stat()
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            "File changed while hashing: " + str(path))
    return h.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def string_list(value, label, nonempty=False):
    require(isinstance(value, list) and (bool(value) or not nonempty), label + " must be a list")
    require(all(isinstance(v, str) and v for v in value), label + " must contain nonempty strings")
    return value


def read_map(root, relative):
    path = safe_path(root, relative)
    data = load_json(path)
    require(isinstance(data, dict) and type(data.get("schema_version")) is int
            and data["schema_version"] == 1, "pipeline map requires schema_version 1")
    require(isinstance(data.get("purpose"), str) and data["purpose"].strip(), "Map purpose is required")
    entries = data.get("entry_points")
    require(isinstance(entries, list) and entries, "Map entry_points cannot be empty")
    refs = set()
    for item in entries:
        require(isinstance(item, dict) and isinstance(item.get("description"), str), "Invalid entry point")
        safe_path(root, item.get("path"))
        refs.add(item["path"])
    flows = data.get("flows", [])
    require(isinstance(flows, list), "flows must be a list")
    for flow in flows:
        require(isinstance(flow, dict) and isinstance(flow.get("name"), str), "Invalid flow")
        steps = flow.get("steps", [])
        require(isinstance(steps, list), "Flow steps must be a list")
        for step in steps:
            require(isinstance(step, dict) and isinstance(step.get("description"), str), "Invalid flow step")
            safe_path(root, step.get("path"))
            refs.add(step["path"])
    watch = data.get("watch")
    require(isinstance(watch, dict), "watch is required")
    includes = string_list(watch.get("include"), "watch.include", True)
    excludes = string_list(watch.get("exclude", []), "watch.exclude")
    for pattern in includes + excludes:
        require(not Path(pattern).is_absolute() and ".." not in Path(pattern).parts,
                "Watch patterns must stay inside project root")
    return path, data, refs


def source_state(root, relative):
    path, data, refs = read_map(root, relative)
    files = set()
    excludes = data["watch"].get("exclude", [])
    for pattern in data["watch"]["include"]:
        for candidate in root.glob(pattern):
            rel = candidate.relative_to(root)
            if any(part in IGNORED_PARTS for part in rel.parts):
                continue
            if any(fnmatch.fnmatchcase(rel.as_posix(), p) for p in excludes):
                continue
            if candidate.is_file():
                safe_path(root, rel.as_posix())
                files.add(rel.as_posix())
    missing = []
    for ref in refs:
        target = safe_path(root, ref)
        if target.is_file():
            files.add(ref)
        else:
            missing.append(ref)
    require(len(files) <= 10000, "Watch scope exceeds 10000 files; narrow the include patterns")
    hashes = {rel: digest(safe_path(root, rel)) for rel in sorted(files)}
    return {"schema_version": 1, "map_path": path.relative_to(root).as_posix(),
            "map_sha256": digest(path), "watch": data["watch"], "files": hashes,
            "missing_references": sorted(missing)}


def check_sources(root, map_relative, baseline_relative):
    current = source_state(root, map_relative)
    baseline = load_json(safe_path(root, baseline_relative))
    require(isinstance(baseline, dict) and type(baseline.get("schema_version")) is int
            and baseline["schema_version"] == 1, "Invalid source baseline version")
    previous = baseline.get("files")
    require(isinstance(previous, dict), "Invalid source baseline files")
    for path, sha in previous.items():
        safe_path(root, path)
        require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha), "Invalid baseline fingerprint")
    now = current["files"]
    added = sorted(set(now) - set(previous))
    removed = sorted(set(previous) - set(now))
    changed = sorted(p for p in set(now) & set(previous) if now[p] != previous[p])
    map_changed = (baseline.get("map_sha256") != current["map_sha256"]
                   or baseline.get("map_path") != current["map_path"]
                   or baseline.get("watch") != current["watch"])
    stale = bool(added or removed or changed or map_changed or current["missing_references"])
    return {"status": "changed" if stale else "unchanged", "added": added, "removed": removed,
            "changed": changed, "map_changed": map_changed,
            "missing_references": current["missing_references"], "watch": current["watch"],
            "watched_file_count": len(now), "semantic_consistency_verified": False}, int(stale)


def json_pointer(value, pointer):
    require(isinstance(pointer, str) and (not pointer or pointer.startswith("/")), "Invalid JSON pointer")
    if not pointer:
        return value
    for raw in pointer[1:].split("/"):
        require(not re.search(r"~(?![01])", raw), "Invalid JSON pointer escape")
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[token]
        elif isinstance(value, list):
            require(bool(re.fullmatch(r"0|[1-9][0-9]*", token)), "Invalid array index")
            value = value[int(token)]
        else:
            raise ValueError("JSON pointer crosses a scalar")
    return value


def json_equal(actual, expected):
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(json_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(json_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def validate_text_checks(checks, file_check=False):
    require(isinstance(checks, dict), "Text/file assertions must be an object")
    allowed = {"contains", "not_contains", "json"} | ({"path", "fresh"} if file_check else set())
    require(not set(checks) - allowed, "Unknown assertion fields: " + str(sorted(set(checks) - allowed)))
    for field in ("contains", "not_contains"):
        string_list(checks.get(field, []), field)
    items = checks.get("json", [])
    require(isinstance(items, list), "json assertions must be a list")
    for item in items:
        require(isinstance(item, dict) and set(item) == {"pointer", "equals"}, "JSON assertion needs pointer and equals")
        pointer = item["pointer"]
        require(isinstance(pointer, str) and (not pointer or pointer.startswith("/")), "Invalid JSON pointer")
        require(not re.search(r"~(?![01])", pointer), "Invalid JSON pointer escape")
    if file_check:
        require(type(checks.get("fresh", True)) is bool, "fresh must be boolean")


def read_suite(root, relative):
    path = safe_path(root, relative)
    data = load_json(path)
    require(isinstance(data, dict) and set(data) == {"schema_version", "cases"}
            and type(data["schema_version"]) is int and data["schema_version"] == 1,
            "Suite requires schema_version 1 and cases")
    require(isinstance(data["cases"], list) and data["cases"], "Suite cases cannot be empty")
    ids = set()
    for case in data["cases"]:
        require(isinstance(case, dict) and not set(case) - {"id", "kind", "description", "command", "inputs", "timeout_seconds", "expect"},
                "Unknown or invalid case fields")
        cid = case.get("id")
        require(isinstance(cid, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", cid), "Invalid case id")
        require(cid not in ids, "Duplicate case id: " + cid)
        ids.add(cid)
        string_list(case.get("command"), "command", True)
        for input_path in string_list(case.get("inputs", []), "inputs"):
            safe_path(root, input_path)
        timeout = case.get("timeout_seconds", 30)
        require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 300,
                "timeout_seconds must be between 0 and 300")
        expect = case.get("expect")
        require(isinstance(expect, dict) and expect and not set(expect) - {"returncode", "stdout", "files"}, "Invalid expect fields")
        if "returncode" in expect:
            require(type(expect["returncode"]) is int, "returncode must be an integer")
        if "stdout" in expect:
            validate_text_checks(expect["stdout"])
        output_files = expect.get("files", [])
        require(isinstance(output_files, list), "expect.files must be a list")
        for output in output_files:
            validate_text_checks(output, True)
            safe_path(root, output.get("path"))
        meaningful = ("returncode" in expect or bool(output_files)
                      or any(expect.get("stdout", {}).get(k) for k in ("contains", "not_contains", "json")))
        require(meaningful, "Case has no assertions: " + cid)
    return path, data


def compare_text(text, spec, label):
    failures = []
    for term in spec.get("contains", []):
        if term not in text:
            failures.append(label + ": missing expected text " + repr(term))
    for term in spec.get("not_contains", []):
        if term in text:
            failures.append(label + ": forbidden text " + repr(term))
    if spec.get("json"):
        try:
            value = json.loads(text, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
        except (ValueError, TypeError):
            return failures + [label + ": invalid JSON"]
        for item in spec["json"]:
            try:
                actual = json_pointer(value, item["pointer"])
                if not json_equal(actual, item["equals"]):
                    failures.append(label + ": mismatch at " + repr(item["pointer"]))
            except (KeyError, IndexError, ValueError, TypeError):
                failures.append(label + ": missing/invalid pointer " + repr(item["pointer"]))
    return failures


def signature(path):
    if not path.is_file():
        return None
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, digest(path))


def input_fingerprints(root, paths):
    fingerprints = {}
    for name in paths:
        path = safe_path(root, name)
        try:
            fingerprints[name] = digest(path) if path.is_file() else None
        except OSError:
            fingerprints[name] = None
    return fingerprints


def optional_source_state(root, map_relative):
    if not safe_path(root, map_relative).exists():
        return None
    return source_state(root, map_relative)


def run_evaluation(root, suite_relative, output_relative, selected, map_relative):
    suite_path, suite = read_suite(root, suite_relative)
    suite_sha = digest(suite_path)
    ids = {case["id"] for case in suite["cases"]}
    require(not set(selected) - ids, "Unknown selected case ids")
    output_path = safe_path(root, output_relative)
    protected = {suite_path, safe_path(root, map_relative), safe_path(root, BASELINE_DEFAULT)}
    protected.update(safe_path(root, item["path"]) for case in suite["cases"] for item in case["expect"].get("files", []))
    protected.update(safe_path(root, p) for case in suite["cases"] for p in case.get("inputs", []))
    require(output_path not in protected, "Report cannot overwrite suite, map, baseline, input or expected artifact")
    source_before = optional_source_state(root, map_relative)
    if source_before is not None:
        require(output_path.relative_to(root).as_posix() not in source_before["files"], "Report cannot overwrite watched source")
    results = []
    for case in suite["cases"]:
        if selected and case["id"] not in selected:
            continue
        spec = case["expect"]
        inputs_before = input_fingerprints(root, case.get("inputs", []))
        command = [sys.executable if token == "{python}" else token for token in case["command"]]
        unavailable = [name for name, fingerprint in inputs_before.items() if fingerprint is None]
        if unavailable:
            results.append({"id": case["id"], "kind": case.get("kind", "unspecified"),
                            "status": "failed", "executed": False, "returncode": None,
                            "command": command, "duration_seconds": 0, "stdout": "", "stderr": "", "artifacts": [],
                            "input_fingerprints": inputs_before, "inputs_declared": True,
                            "inputs_changed_during_case": False,
                            "failures": ["Missing or unreadable input: " + name for name in unavailable]})
            continue
        before = {item["path"]: signature(safe_path(root, item["path"])) for item in spec.get("files", [])}
        started = time.monotonic()
        failures = []
        stdout, stderr, returncode = "", "", None
        try:
            process = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=case.get("timeout_seconds", 30), shell=False)
            stdout, stderr, returncode = process.stdout, process.stderr, process.returncode
            if returncode != spec.get("returncode", 0):
                failures.append("Unexpected return code: " + str(returncode))
        except subprocess.TimeoutExpired:
            failures.append("Command timed out")
        except OSError as exc:
            failures.append("Command could not run: " + str(exc))
        failures.extend(compare_text(stdout, spec.get("stdout", {}), "stdout"))
        artifacts = []
        for item in spec.get("files", []):
            path = safe_path(root, item["path"])
            after = signature(path)
            if after is None:
                failures.append("Missing output: " + item["path"])
                continue
            if item.get("fresh", True) and before[item["path"]] == after:
                failures.append("Stale output not rewritten by this case: " + item["path"])
            try:
                failures.extend(compare_text(path.read_text(encoding="utf-8"), item, item["path"]))
            except UnicodeError:
                if any(item.get(k) for k in ("contains", "not_contains", "json")):
                    failures.append("Output is not UTF-8 text: " + item["path"])
            artifacts.append({"path": item["path"], "sha256": after[3]})
        inputs_changed = inputs_before != input_fingerprints(root, case.get("inputs", []))
        if inputs_changed:
            failures.append("Declared input changed during this case")
        results.append({"id": case["id"], "kind": case.get("kind", "unspecified"),
                        "status": "failed" if failures else "passed", "returncode": returncode,
                        "executed": True, "duration_seconds": round(time.monotonic() - started, 6), "command": command,
                        "stdout": stdout, "stderr": stderr, "failures": failures, "artifacts": artifacts,
                        "inputs_declared": bool(case.get("inputs")), "input_fingerprints": inputs_before,
                        "inputs_changed_during_case": inputs_changed})
    source_after = optional_source_state(root, map_relative)
    source_changed = source_before != source_after
    suite_changed = digest(suite_path) != suite_sha
    failed = any(case["status"] == "failed" for case in results) or source_changed or suite_changed
    executed = sum(case["executed"] for case in results)
    report = {"schema_version": 1, "status": "failed" if failed else "passed",
              "suite_sha256": suite_sha, "suite_changed_during_run": suite_changed,
              "suite_case_count": len(suite["cases"]), "executed_case_count": executed,
              "all_cases_executed": executed == len(suite["cases"]),
              "source_before": source_before, "source_changed_during_run": source_changed,
              "results": results}
    write_json(output_path, report)
    return {"status": report["status"], "report": output_path.relative_to(root).as_posix(),
            "all_cases_executed": report["all_cases_executed"],
            "executed_case_count": executed, "suite_case_count": len(suite["cases"]),
            "source_changed_during_run": source_changed, "suite_changed_during_run": suite_changed,
            "results": [{"id": c["id"], "status": c["status"], "failures": c["failures"]} for c in results]}, int(failed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Project root, not kit root")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "snapshot", "map"):
        sub = commands.add_parser(name)
        sub.add_argument("--map", default=MAP_DEFAULT)
        sub.add_argument("--baseline", default=BASELINE_DEFAULT)
    evaluation = commands.add_parser("eval")
    evaluation.add_argument("--suite", default=SUITE_DEFAULT)
    evaluation.add_argument("--output", default=REPORT_DEFAULT)
    evaluation.add_argument("--case", action="append", default=[])
    evaluation.add_argument("--map", default=MAP_DEFAULT)
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        require(root.is_dir(), "Project root is not a directory")
        if args.command == "check":
            result, code = check_sources(root, args.map, args.baseline)
        elif args.command == "snapshot":
            result = source_state(root, args.map)
            require(result["files"], "No watched source files; do not create an empty baseline")
            require(not result["missing_references"], "Map references are missing: " + str(result["missing_references"]))
            target = safe_path(root, args.baseline)
            require(target != safe_path(root, args.map), "Baseline cannot overwrite map")
            write_json(target, result)
            result = {"status": "baseline_recorded", "watched_file_count": len(result["files"]),
                      "semantic_consistency_verified": False}
            code = 0
        elif args.command == "map":
            _, data, refs = read_map(root, args.map)
            result = {"purpose": data["purpose"], "entry_points": data["entry_points"],
                      "flows": data.get("flows", []), "dependencies": data.get("dependencies", []),
                      "commands": data.get("commands", {}),
                      "missing_references": sorted(p for p in refs if not safe_path(root, p).is_file()),
                      "freshness": "Run check separately; map rendering does not assert freshness"}
            code = 0
        else:
            result, code = run_evaluation(root, args.suite, args.output, args.case, args.map)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return code
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
