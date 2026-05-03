"""Built-in detection rules."""

from __future__ import annotations

from collections.abc import Iterable

from agentguard.rules.base import Rule
from agentguard.rules.confused_deputy import ConfusedDeputyRule
from agentguard.rules.prompt_injection import SystemPromptInjectionRule


def all_rules() -> Iterable[Rule]:
    """Return one fresh instance of each built-in rule."""
    yield ConfusedDeputyRule()
    yield SystemPromptInjectionRule()


__all__ = [
    "ConfusedDeputyRule",
    "Rule",
    "SystemPromptInjectionRule",
    "all_rules",
]
