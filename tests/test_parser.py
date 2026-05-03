"""Tests for the LangGraph parser."""

from __future__ import annotations

from pathlib import Path

from injectguard.ir import ToolClassification, TrustLevel
from injectguard.parsers import LangGraphParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_parser_finds_tools_and_classifies_them() -> None:
    parser = LangGraphParser()
    tools, agents = parser.parse_file(FIXTURES / "vulnerable" / "confused_deputy_email.py")

    names = {t.name for t in tools}
    assert names == {"read_email", "send_email"}

    by_name = {t.name: t for t in tools}
    assert by_name["read_email"].classification == ToolClassification.SOURCE
    assert by_name["read_email"].trust_of_output == TrustLevel.UNTRUSTED
    assert by_name["send_email"].classification == ToolClassification.SINK
    assert by_name["send_email"].privilege >= 2
    assert by_name["send_email"].reversible is False

    assert len(agents) == 1
    agent = agents[0]
    assert agent.framework == "langgraph"
    assert {t.name for t in agent.tools} == {"read_email", "send_email"}
    assert agent.system_prompt_is_dynamic is False


def test_parser_detects_dynamic_prompt() -> None:
    parser = LangGraphParser()
    _, agents = parser.parse_file(FIXTURES / "vulnerable" / "dynamic_prompt.py")
    assert len(agents) == 1
    agent = agents[0]
    assert agent.system_prompt_is_dynamic is True
    assert "user_request" in agent.system_prompt_taint_sources


def test_parser_recognizes_interrupt_before() -> None:
    parser = LangGraphParser()
    _, agents = parser.parse_file(FIXTURES / "safe" / "email_with_interrupt.py")
    assert len(agents) == 1
    assert agents[0].interrupts_before == ["send_email"]


def test_parser_handles_static_prompt() -> None:
    parser = LangGraphParser()
    _, agents = parser.parse_file(FIXTURES / "safe" / "static_prompt.py")
    assert len(agents) == 1
    assert agents[0].system_prompt_is_dynamic is False
    assert agents[0].system_prompt_taint_sources == []
