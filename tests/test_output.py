"""Tests for output formatters."""

from __future__ import annotations

import json
from pathlib import Path

from injectguard.engine import Scanner
from injectguard.output import format_json, format_sarif

FIXTURES = Path(__file__).parent / "fixtures"


def test_sarif_is_valid_json_and_has_results() -> None:
    result = Scanner().scan(FIXTURES / "vulnerable" / "confused_deputy_email.py")
    text = format_sarif(result)
    doc = json.loads(text)

    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["tool"]["driver"]["name"] == "injectguard"
    rule_ids = {r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]}
    assert {"IG001", "IG002"}.issubset(rule_ids)

    results = doc["runs"][0]["results"]
    assert any(r["ruleId"] == "IG001" for r in results)
    for r in results:
        assert "physicalLocation" in r["locations"][0]
        assert "security-severity" in r["properties"]


def test_json_output_round_trips() -> None:
    result = Scanner(include_tests=True).scan(FIXTURES / "vulnerable")
    payload = json.loads(format_json(result))
    assert payload["files_scanned"] >= 3
    assert payload["findings"]
    for f in payload["findings"]:
        assert f["rule_id"].startswith("IG")
        assert f["severity"] in {"info", "low", "medium", "high", "critical"}
