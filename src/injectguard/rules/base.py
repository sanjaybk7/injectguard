"""Base classes for detection rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import ClassVar

from injectguard.ir import Agent, Finding, Tool
from injectguard.taxonomy import Taxonomy


@dataclass
class RuleContext:
    """Read-only context handed to rules at evaluation time."""

    tools: list[Tool] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)
    taxonomy: Taxonomy | None = None


class Rule(ABC):
    """Base class for a detection rule."""

    id: ClassVar[str]
    name: ClassVar[str]
    owasp_llm_ids: ClassVar[list[str]] = []

    @abstractmethod
    def check(self, ctx: RuleContext) -> Iterable[Finding]:
        """Return zero or more findings for the given context."""
        raise NotImplementedError
