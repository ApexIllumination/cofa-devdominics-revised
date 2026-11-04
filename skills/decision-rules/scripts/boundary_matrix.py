"""Generate golden case specifications for one confirmed threshold and scoped waiver."""
import argparse
import itertools
import json
from pathlib import Path

OPS = {"<=": lambda x,y: x <= y, "<": lambda x,y: x < y,
       ">=": lambda x,y: x >= y, ">": lambda x,y: x > y}


def matrix(*, rule, operator, limit, step, unit, exception, retained_rule, source):
    """Integer ticks only. The exception waives rule and no other constraint."""
    if not all(isinstance(v,str) and v.strip() for v in (rule, unit, exception, retained_rule, source)):
        raise ValueError("name the rules, unit, confirmed exception and policy source")
    if rule == retained_rule or operator not in OPS:
        raise ValueError("require distinct rules and a confirmed comparison operator")
    if type(limit) is not int or type(step) is not int or step <= 0:
        raise ValueError("use integer ticks and a positive, representable step")
    rows = []
    for offset, waived, violates_other in itertools.product((-1, 0, 1), (False, True), (False, True)):
        value = limit + offset * step
        failures = []
        if not waived and not OPS[operator](value, limit):
            failures.append(rule)
        if violates_other:
            failures.append(retained_rule)
        rows.append(dict(value=value, unit=unit, exception=exception if waived else None,
                         violated_independent_rule=retained_rule if violates_other else None,
                         expected_allowed=not failures, expected_violations=failures, source=source))
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path, help="JSON arguments to matrix()")
    args = parser.parse_args()
    print(json.dumps(matrix(**json.loads(args.policy.read_text())), ensure_ascii=False, indent=2))
