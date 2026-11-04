"""Optional stdio transport. Bind the database path when starting the server."""
import argparse
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from decision_log import append, recall, check_current
from typing import Any


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    db = parser.parse_args().db.resolve()
    server = FastMCP("decision-log")

    @server.tool()
    def record_event(decision_id: str, event_id: str, kind: str, actor: str,
                     source: str, detail: dict[str, Any]) -> str:
        """Append a sourced answer, decision or verification. Unknown facts stay unknown."""
        return append(db, decision_id, event_id, kind, actor, source, detail)

    @server.tool()
    def recall_decision(decision_id: str) -> list[dict]:
        """Retrieve the sourced history of this decision in insertion order."""
        return recall(db, decision_id)

    @server.tool()
    def current_pass(decision_id: str, check_id: str, input_id: str, revision: str,
                     rule_ids: list[str]) -> dict:
        """Assess whether the historical check still supports a PASS for this input."""
        return check_current(db, decision_id, check_id, input_id, revision, rule_ids)

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
