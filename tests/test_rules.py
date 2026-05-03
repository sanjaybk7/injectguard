"""End-to-end rule tests."""

from __future__ import annotations

from pathlib import Path

from injectguard.engine import Scanner
from injectguard.ir import Severity

FIXTURES = Path(__file__).parent / "fixtures"


def _scan(path: Path) -> list[str]:
    result = Scanner().scan(path)
    return [f.rule_id for f in result.findings]


def test_confused_deputy_email_fires_ig001() -> None:
    rule_ids = _scan(FIXTURES / "vulnerable" / "confused_deputy_email.py")
    assert "IG001" in rule_ids


def test_web_to_shell_fires_ig001_critical() -> None:
    result = Scanner().scan(FIXTURES / "vulnerable" / "web_to_shell.py")
    ig001 = [f for f in result.findings if f.rule_id == "IG001"]
    assert ig001, "expected IG001 to fire on web -> shell agent"
    assert any(f.severity == Severity.CRITICAL for f in ig001), (
        "shell sink should be critical severity"
    )


def test_dynamic_prompt_fires_ig002() -> None:
    rule_ids = _scan(FIXTURES / "vulnerable" / "dynamic_prompt.py")
    assert "IG002" in rule_ids


def test_email_with_interrupt_does_not_fire_ig001() -> None:
    rule_ids = _scan(FIXTURES / "safe" / "email_with_interrupt.py")
    assert "IG001" not in rule_ids


def test_sources_only_does_not_fire_ig001() -> None:
    rule_ids = _scan(FIXTURES / "safe" / "sources_only.py")
    assert "IG001" not in rule_ids


def test_static_prompt_does_not_fire_ig002() -> None:
    rule_ids = _scan(FIXTURES / "safe" / "static_prompt.py")
    assert "IG002" not in rule_ids


def test_directory_scan_aggregates_findings() -> None:
    # Fixtures live under tests/, which is filtered out by default. Opt in.
    result = Scanner(include_tests=True).scan(FIXTURES / "vulnerable")
    rule_ids = {f.rule_id for f in result.findings}
    assert "IG001" in rule_ids
    assert "IG002" in rule_ids
    assert result.files_scanned >= 3


def test_directory_scan_skips_tests_by_default() -> None:
    # Without include_tests=True, fixtures under tests/ are skipped entirely.
    result = Scanner().scan(FIXTURES / "vulnerable")
    assert result.files_scanned == 0
    assert result.findings == []
