"""Read-only diagnostics for UTF-8 CSV and JSON record arrays."""
import argparse
import csv
import json
from collections import defaultdict
from decimal import Decimal, DecimalException, Inexact, InvalidOperation, localcontext
from pathlib import Path


def unique_fields(pairs):
    fields = {}
    for name, value in pairs:
        if name in fields:
            raise ValueError(f"duplicate field: {name!r}")
        fields[name] = value
    return fields


def reject_constant(value):
    raise ValueError(f"invalid JSON number: {value}")


def load(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        if path.suffix.lower() == ".json":
            rows = json.load(stream, object_pairs_hook=unique_fields,
                             parse_float=Decimal, parse_constant=reject_constant)
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise ValueError("expected a JSON array of objects")
            return list(dict.fromkeys(k for row in rows for k in row)), rows
        if path.suffix.lower() != ".csv":
            raise ValueError("expected a .csv or .json file")
        reader = csv.reader(stream, strict=True)
        fields = next(reader, [])
        if not fields or not all(fields) or len(set(fields)) != len(fields):
            raise ValueError("CSV header is missing, empty or duplicated")
        rows = []
        for i, values in enumerate(reader, 1):
            if len(values) != len(fields):
                raise ValueError(f"record {i}: expected {len(fields)} fields, got {len(values)}")
            rows.append(dict(zip(fields, values)))
        return fields, rows


def blank(value):
    return value is None or isinstance(value, str) and not value.strip()


def number(value):
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        return None
    if isinstance(value, str) and "_" in value:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def key_of(value):
    if blank(value):
        return None
    if isinstance(value, str):
        return ("text", value)
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return ("number", value)
    raise ValueError(f"expected a string or number as key, got {value!r}")


def observe(stats, record, limit):
    stats["count"] += 1
    if len(stats["records"]) < limit:
        stats["records"].append(record)


def bucket():
    return {"count": 0, "records": []}


def required(fields, names):
    for name in names:
        if name is not None and name not in fields:
            raise ValueError(f"column {name!r} not found in {fields!r}")


def profile(fields, rows, key, limit):
    required(fields, [key])
    columns = {f: {"missing": bucket(), "zero": bucket()} for f in fields}
    groups = defaultdict(list)
    for i, row in enumerate(rows, 1):
        for f, stats in columns.items():
            value = row.get(f)
            if blank(value):
                observe(stats["missing"], i, limit)
            elif number(value) == 0:
                observe(stats["zero"], i, limit)
        if key is not None:
            identity = key_of(row.get(key))
            if identity is not None:
                groups[identity].append(i)
    report = {"rows": len(rows), "columns": columns}
    if key is not None:
        duplicates = [ids for ids in groups.values() if len(ids) > 1]
        report.update(key=key, duplicate_keys=len(duplicates), duplicates=[
            {"value": rows[ids[0] - 1][key], "count": len(ids), "records": ids[:limit]}
            for ids in duplicates[:limit]])
    return report, groups


def compare(rows, left, reference_groups, measure, limit):
    report = {"type": "left", "before_rows": len(rows), "after_rows": 0}
    issues = {name: bucket() for name in ("missing_key", "unmatched_key", "multiple_matches")}
    totals = [Decimal(0), Decimal(0)]
    known_rows = [0, 0]
    excluded = {name: bucket() for name in ("missing_number", "invalid_number")}
    for i, row in enumerate(rows, 1):
        key = key_of(row.get(left))
        matches = reference_groups.get(key, [])
        copies = max(1, len(matches))
        report["after_rows"] += copies
        reason = None
        if key is None:
            reason = "missing_key"
        elif not matches:
            reason = "unmatched_key"
        elif copies > 1:
            reason = "multiple_matches"
        if reason:
            evidence = {"record": i, "value": row.get(left)}
            if matches:
                evidence.update(match_count=len(matches), reference_records=matches[:limit])
            observe(issues[reason], evidence, limit)
        if measure:
            raw = row.get(measure)
            value = number(raw)
            if value is None:
                observe(excluded["missing_number" if blank(raw) else "invalid_number"], i, limit)
            else:
                totals[0] += value
                totals[1] += value * copies
                known_rows[0] += 1
                known_rows[1] += copies
    report["issues"] = issues
    if measure:
        report["sum"] = dict(column=measure, before=str(totals[0]) if known_rows[0] else None,
                             after=str(totals[1]) if known_rows[1] else None,
                             numeric_rows_before=known_rows[0], numeric_rows_after=known_rows[1],
                             excluded=excluded)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--key", help="input record ID to check for duplicates")
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--join-key", help="input column for the left join")
    parser.add_argument("--reference-key", help="reference column (defaults to join-key)")
    parser.add_argument("--sum", dest="measure", help="additive input column for join comparison")
    parser.add_argument("--limit", default=10, type=int, help="example records per finding")
    args = parser.parse_args()
    if args.limit < 1 or bool(args.reference) != bool(args.join_key):
        parser.error("use --reference and --join-key together; --limit must be positive")
    if not args.reference and (args.reference_key or args.measure):
        parser.error("--reference-key and --sum require --reference")
    try:
        fields, rows = load(args.input)
        required(fields, [args.join_key, args.measure])
        facts, _ = profile(fields, rows, args.key, args.limit)
        report = {"input": dict(path=str(args.input), **facts)}
        if args.reference:
            ref_fields, ref_rows = load(args.reference)
            ref_key = args.reference_key or args.join_key
            summary, groups = profile(ref_fields, ref_rows, ref_key, args.limit)
            report["reference"] = dict(path=str(args.reference), **summary)
            with localcontext() as ctx:
                ctx.traps[Inexact] = True
                report["join"] = compare(rows, args.join_key, groups, args.measure, args.limit)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    except (ValueError, OSError, csv.Error, DecimalException) as error:
        parser.exit(2, f"diagnosis failed: {error}\n")


if __name__ == "__main__":
    main()
