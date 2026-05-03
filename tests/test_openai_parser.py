"""Tests for the OpenAI Agents SDK parser."""

from __future__ import annotations

from pathlib import Path

from injectguard.engine import Scanner
from injectguard.ir import Severity, ToolClassification, TrustLevel
from injectguard.parsers import OpenAIAgentsParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_parser_extracts_function_tools_and_agent() -> None:
    parser = OpenAIAgentsParser()
    tools, agents = parser.parse_file(FIXTURES / "vulnerable" / "openai_email.py")

    assert {t.name for t in tools} == {"read_email", "send_email"}
    by_name = {t.name: t for t in tools}
    assert by_name["read_email"].classification == ToolClassification.SOURCE
    assert by_name["read_email"].trust_of_output == TrustLevel.UNTRUSTED
    assert by_name["send_email"].is_sink
    assert by_name["send_email"].privilege >= 2

    assert len(agents) == 1
    agent = agents[0]
    assert agent.framework == "openai-agents"
    assert agent.name == "inbox-agent"
    assert {t.name for t in agent.tools} == {"read_email", "send_email"}


def test_parser_detects_dynamic_instructions() -> None:
    parser = OpenAIAgentsParser()
    _, agents = parser.parse_file(FIXTURES / "vulnerable" / "openai_dynamic_prompt.py")
    assert len(agents) == 1
    assert agents[0].system_prompt_is_dynamic is True
    assert "user_request" in agents[0].system_prompt_taint_sources


def test_parser_does_not_match_non_agents_file() -> None:
    parser = OpenAIAgentsParser()
    tools, agents = parser.parse_file(FIXTURES / "safe" / "not_an_agent_file.py")
    assert tools == []
    assert agents == []


def test_stop_on_first_tool_gates_all_sinks() -> None:
    result = Scanner().scan(FIXTURES / "safe" / "openai_stop_on_first_tool.py")
    assert "IG001" not in {f.rule_id for f in result.findings}


def test_stop_at_tools_gates_named_sink() -> None:
    result = Scanner().scan(FIXTURES / "safe" / "openai_stop_at_tools.py")
    assert "IG001" not in {f.rule_id for f in result.findings}


def test_openai_email_fires_ig001_high() -> None:
    result = Scanner().scan(FIXTURES / "vulnerable" / "openai_email.py")
    ig001 = [f for f in result.findings if f.rule_id == "IG001"]
    assert ig001
    assert any(f.severity in (Severity.HIGH, Severity.CRITICAL) for f in ig001)


def test_openai_dynamic_prompt_fires_ig002() -> None:
    result = Scanner().scan(FIXTURES / "vulnerable" / "openai_dynamic_prompt.py")
    assert "IG002" in {f.rule_id for f in result.findings}
