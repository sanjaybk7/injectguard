"""Plain JSON output for machine consumers."""

from __future__ import annotations

import json
from typing import Any

from agentguard.engine import ScanResult


def format_json(result: ScanResult) -> str:
    """Serialize a scan result as JSON."""
    payload: dict[str, Any] = {
        "files_scanned": result.files_scanned,
        "tools_seen": result.tools_seen,
        "agents_seen": result.agents_seen,
        "findings": [_finding_to_dict(f) for f in result.findings],
    }
    return json.dumps(payload, indent=2)


def _finding_to_dict(finding: Any) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "rule_name": finding.rule_name,
        "severity": finding.severity.value,
        "message": finding.message,
        "owasp_llm_ids": list(finding.owasp_llm_ids),
        "location": _location_to_dict(finding.location),
        "related_locations": [_location_to_dict(rel) for rel in finding.related_locations],
        "fix_hint": finding.fix_hint,
    }


def _location_to_dict(loc: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "file": str(loc.file),
        "line": loc.line,
        "column": loc.column,
    }
    if str(loc.file).endswith(".ipynb"):
        # Notebook locations: the column field is repurposed as the cell index.
        out["cell"] = loc.column
        # Make column meaningless for notebooks, since it's not a real column offset.
        out["column"] = 0
    return out
