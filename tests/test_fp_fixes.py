"""Tests for the false-positive fixes added after real-world scanning.

Each fixture in tests/fixtures/safe/ that exercises a previously-noisy pattern
has a corresponding assertion here that confirms it stays clean.
"""

from __future__ import annotations

from pathlib import Path

from agentic_guard.engine import Scanner

FIXTURES = Path(__file__).parent / "fixtures"


def _rule_ids(path: Path) -> set[str]:
    return {f.rule_id for f in Scanner().scan(path).findings}


def test_openai_constant_prompt_no_findings() -> None:
    """instructions=ANALYST_PROMPT where ANALYST_PROMPT = '...' must not fire IG002."""
    assert "IG002" not in _rule_ids(FIXTURES / "safe" / "openai_constant_prompt.py")


def test_openai_callable_instructions_no_findings() -> None:
    """instructions=callable_function must not fire IG002 (canonical SDK pattern)."""
    assert "IG002" not in _rule_ids(FIXTURES / "safe" / "openai_callable_instructions.py")


def test_openai_safe_helper_no_findings() -> None:
    """instructions=prompt_with_handoff_instructions('...') must not fire IG002."""
    assert "IG002" not in _rule_ids(FIXTURES / "safe" / "openai_safe_helper.py")


def test_langgraph_constant_prompt_no_findings() -> None:
    """prompt=SYSTEM_PROMPT where SYSTEM_PROMPT = '...' must not fire IG002."""
    assert "IG002" not in _rule_ids(FIXTURES / "safe" / "langgraph_constant_prompt.py")


def test_dynamic_prompt_still_fires() -> None:
    """Regression: f-string with truly user-controlled var must still fire IG002."""
    assert "IG002" in _rule_ids(FIXTURES / "vulnerable" / "dynamic_prompt.py")


def test_openai_dynamic_prompt_still_fires() -> None:
    """Regression: same for OpenAI SDK dynamic prompt fixture."""
    assert "IG002" in _rule_ids(FIXTURES / "vulnerable" / "openai_dynamic_prompt.py")
