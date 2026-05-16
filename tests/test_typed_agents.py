"""Tests for ``Agent[T](...)`` generic-subscript call recognition (PR #2).

These tests must FAIL on the Fix 1 branch (where ``call_base_name`` only
handles ``ast.Name`` and ``ast.Attribute``) and PASS after the
``ast.Subscript`` handling lands.

The five fixtures cover each canonical usage observed in the OpenAI Agents
SDK official examples + docs:

  1. ``Agent[UserContext](...)`` — user-defined context (docs/agents.md,
     examples/customer_service/main.py)
  2. ``Agent[None](...)`` — None context (examples/agent_patterns/llm_as_a_judge.py)
  3. Multi-agent handoff with source + sink + cross-module prompt — the
     integration test that validates Fix 1 + PR #2 compose correctly
  4. ``return Agent[T](...)`` inside a factory function
     (examples/sandbox/healthcare_support/support_agents.py)
  5. ``import agents; agents.Agent[T](...)`` — attribute-access subscript form
"""

from __future__ import annotations

from pathlib import Path

from agentic_guard.engine import Scanner
from agentic_guard.parsers import OpenAIAgentsParser

FIXTURES = Path(__file__).parent / "fixtures" / "typed_agents"


def _agents_for(path: Path) -> int:
    """Parser-level: how many agents did OpenAIAgentsParser extract?"""
    parser = OpenAIAgentsParser()
    _, agents = parser.parse_file(path)
    return len(agents)


def _rule_ids(path: Path) -> set[str]:
    return {f.rule_id for f in Scanner(include_tests=True).scan(path).findings}


# Pattern 1: Agent[UserContext](...)
def test_user_context_typed_agent_is_recognized() -> None:
    assert _agents_for(FIXTURES / "user_context.py") == 1


# Pattern 2: Agent[None](...)
def test_none_typed_agent_is_recognized() -> None:
    assert _agents_for(FIXTURES / "none_context.py") == 1


# Pattern 3: integration — multi-agent typed handoff with cross-module prompt
def test_typed_handoff_integration_ig001_fires_ig002_does_not() -> None:
    """The keystone test: validates Fix 1 + PR #2 compose correctly.

    Two typed agents: ``support_agent`` has read_email + send_email
    (source + sink) and must trip IG001. Both agents' instructions are
    module-level literals imported from ``prompts.py`` — Fix 1's
    cross-module resolver must keep IG002 silent now that PR #2 lets the
    parser see these calls in the first place.
    """
    rule_ids = _rule_ids(FIXTURES / "handoff_integration")
    assert "IG001" in rule_ids, "expected confused-deputy on source+sink typed agent"
    assert "IG002" not in rule_ids, (
        "cross-module SUPPORT_PROMPT / TRIAGE_PROMPT should resolve to literals; "
        "IG002 firing here means Fix 1 + PR #2 are not composing as intended"
    )


# Pattern 4: nested return Agent[T](...) inside a factory function
def test_factory_function_typed_agent_is_recognized() -> None:
    assert _agents_for(FIXTURES / "factory.py") == 1


# Pattern 5: import agents; agents.Agent[T](...) — attribute-on-subscript
def test_module_attribute_typed_agent_is_recognized() -> None:
    assert _agents_for(FIXTURES / "module_attribute.py") == 1


# Aggregate count: parser should recognize all 5 typed agents above the
# integration directory (excluding it) plus the 2 in the integration sub-package.
def test_typed_agents_aggregate_count() -> None:
    """Whole-directory scan: 4 single-file agents + 2 in handoff_integration = 6."""
    result = Scanner(include_tests=True).scan(FIXTURES)
    assert result.agents_seen == 6, (
        f"expected 6 typed agents recognized, got {result.agents_seen}"
    )
