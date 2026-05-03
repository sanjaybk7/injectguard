"""SARIF v2.1.0 output.

SARIF is the static-analysis interchange format consumed by GitHub code
scanning, VS Code, JetBrains, Sonar, and most other modern code-review
surfaces. Producing valid SARIF is what gets agentguard "for free" into
the GitHub Security tab once the action runs.
"""

from __future__ import annotations

import json
from typing import Any

from agentguard import __version__
from agentguard.engine import ScanResult
from agentguard.ir import Severity
from agentguard.rules import all_rules

# SARIF only has three levels — map our 5-band severity into them.
_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "none",
}

# GitHub uses these to display "high/critical" badges on the Security tab.
_SECURITY_SEVERITY = {
    Severity.CRITICAL: "9.5",
    Severity.HIGH: "8.0",
    Severity.MEDIUM: "5.0",
    Severity.LOW: "3.0",
    Severity.INFO: "1.0",
}


def format_sarif(result: ScanResult) -> str:
    """Serialize a scan result as SARIF v2.1.0."""
    rules_index: dict[str, int] = {}
    rules_block: list[dict[str, Any]] = []
    for i, rule in enumerate(all_rules()):
        rules_index[rule.id] = i
        rules_block.append(
            {
                "id": rule.id,
                "name": _camel(rule.name),
                "shortDescription": {"text": rule.name},
                "fullDescription": {"text": rule.name},
                "helpUri": f"https://github.com/sanjaybk7/agentguard/blob/main/docs/rules/{rule.id}.md",
                "properties": {
                    "tags": ["security", "ai", "agents"] + [f"owasp-{i.lower()}" for i in rule.owasp_llm_ids],
                },
            }
        )

    sarif_results: list[dict[str, Any]] = []
    for finding in result.findings:
        rule_idx = rules_index.get(finding.rule_id, 0)
        sarif_results.append(
            {
                "ruleId": finding.rule_id,
                "ruleIndex": rule_idx,
                "level": _LEVEL.get(finding.severity, "warning"),
                "message": {"text": finding.message},
                "locations": [_loc(finding.location)],
                "relatedLocations": [_loc(loc) for loc in finding.related_locations],
                "properties": {
                    "security-severity": _SECURITY_SEVERITY.get(finding.severity, "5.0"),
                    "owasp-llm": finding.owasp_llm_ids,
                    "fix-hint": finding.fix_hint,
                },
            }
        )

    document: dict[str, Any] = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "agentguard",
                        "version": __version__,
                        "informationUri": "https://github.com/sanjaybk7/agentguard",
                        "rules": rules_block,
                    }
                },
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(document, indent=2)


def _loc(location: Any) -> dict[str, Any]:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": str(location.file)},
            "region": {
                "startLine": location.line,
                "startColumn": max(location.column, 1),
                **(
                    {"endLine": location.end_line}
                    if getattr(location, "end_line", None)
                    else {}
                ),
            },
        }
    }


def _camel(text: str) -> str:
    parts = "".join(c if c.isalnum() or c == " " else " " for c in text).split()
    return "".join(p.capitalize() for p in parts) or "Rule"
