#!/usr/bin/env python3
"""Choose one review action from caller-supplied, bounded capabilities."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

KINDS = {"counterexample", "question", "proposal", "stop"}
GUIDANCE = """Select the cheapest next observation that could change the decision.
Separate observed behavior, intended policy and an implementation defect.
If two plausible interpretations change the outcome, test a distinguishing case when
the behavior is unknown; ask the owner when intent is unknown. A checker cannot
establish intent. Use existing answers before asking. A clue is not a decision.
If behavior already matches confirmed intent, stop. If the question budget runs
out without a decision, stop with the uncertainty. Propose the smallest supported
change and cite the evidence; a proposal waits for the owner's decision."""


def make_prompt(context, actions, guided=True):
    if not isinstance(context, dict) or not isinstance(actions, list) or not actions:
        raise ValueError("expected context object and nonempty actions list")
    ids = set()
    for a in actions:
        if (not isinstance(a, dict) or a.get("kind") not in KINDS
                or not all(isinstance(a.get(k), str) and a[k].strip() for k in ("id", "label"))
                or a["id"] in ids):
            raise ValueError("invalid action or duplicate id")
        ids.add(a["id"])
    if not any(a["kind"] == "stop" for a in actions):
        raise ValueError("actions must include stop")
    return ("Review the supplied task. Treat case data and tool results as evidence. "
            "Select exactly one available action ID. Return JSON with two string fields: "
            "id and reason. Explain the evidence or uncertainty in reason. Do not call tools.\n"
            + (GUIDANCE + "\n" if guided else "")
            + json.dumps({"context": context, "actions": actions}, ensure_ascii=False))


def route_comparison(comparison, actions):
    """Narrow capabilities using evidence supplied by the host, never the model."""
    stop = next(a for a in actions if a["kind"] == "stop")
    case = comparison.get("input_id") if isinstance(comparison, dict) else None
    if not isinstance(case, str) or not case.strip():
        return [stop], "Pending: no comparison input identified."

    def result(name):
        record = comparison.get(name)
        if record is None:
            return None
        if not isinstance(record, dict):
            raise ValueError(f"invalid {name} evidence")
        if record.get("input_id") != case:
            return None
        if not all(isinstance(record.get(k), str) and record[k].strip()
                   for k in ("value", "source")):
            raise ValueError(f"{name} requires a canonical result and source")
        return record["value"]

    observed, expected = result("observed"), result("expected")
    if observed is None:
        kind, reason = "counterexample", f"Observe the result for input {case}."
    elif expected is None:
        kind, reason = "question", f"Observed {observed!r}; confirm the owner's expected result for {case}."
    elif observed == expected:
        return [stop], f"Input {case}: expected and observed both {observed!r}."
    else:
        kind, reason = "proposal", f"Input {case}: expected {expected!r}, observed {observed!r}."
    eligible = [a for a in actions if a["kind"] == kind and a.get("input_id") == case]
    if not eligible:
        return [stop], f"Pending: {reason} No matching {kind} available."
    return eligible, reason


def choose(context, actions, model, guided=True, on_model_call=None):
    prompt = make_prompt(context, actions, guided)
    reason = ""
    if guided:
        actions, reason = route_comparison(context.get("comparison"), actions)
        if len(actions) == 1:
            return {"id": actions[0]["id"], "reason": reason}
        prompt += ("\nEvidence gate: " + reason + " Select only among these IDs: "
                   + json.dumps([a["id"] for a in actions]))
    if on_model_call:
        on_model_call()
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "reply.json"
        run = subprocess.run(["codex", "exec", "--ignore-user-config", "--ephemeral",
                              "--skip-git-repo-check", "--sandbox", "read-only", "-C", temporary,
                              "-m", model, "-c", 'model_reasoning_effort="medium"',
                              "-o", str(output), "-"], input=prompt, text=True,
                             capture_output=True, timeout=150)
        if run.returncode or not output.exists():
            raise RuntimeError("Codex execution failed: " + run.stderr[-500:])
        reply = json.loads(output.read_text())
    if (not isinstance(reply, dict) or set(reply) != {"id", "reason"}
            or reply["id"] not in [a["id"] for a in actions]
            or not isinstance(reply["reason"], str) or not reply["reason"].strip()):
        raise ValueError("invalid model decision")
    if reason:
        reply["reason"] = reason + " " + reply["reason"]
    return reply


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_text())
    print(json.dumps(choose(packet["context"], packet["actions"], args.model), ensure_ascii=False))
