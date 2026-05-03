"""Intermediate representation for parsed agent code.

Parsers normalize framework-specific code (LangGraph, OpenAI Agents SDK, MCP)
into these shared types so detection rules can be framework-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    """Severity level for findings, modeled loosely on CVSS qualitative bands."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TrustLevel(StrEnum):
    """Trust classification for data flowing through an agent."""

    TRUSTED = "trusted"
    MIXED = "mixed"
    UNTRUSTED = "untrusted"


class ToolClassification(StrEnum):
    """How a tool participates in taint flow.

    A tool can be:
      - SOURCE: returns data from outside the trust boundary (web, email, files).
      - SINK: causes a side effect that an attacker would want to control.
      - BOTH: e.g. a database tool that both reads and writes.
      - NEUTRAL: pure compute, no taint relevance.
    """

    SOURCE = "source"
    SINK = "sink"
    BOTH = "both"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class SourceLocation:
    """Where in a source file something is defined."""

    file: Path
    line: int
    column: int = 0
    end_line: int | None = None
    end_column: int | None = None


@dataclass
class Tool:
    """A tool exposed to an agent (a callable the LLM can invoke)."""

    name: str
    location: SourceLocation
    classification: ToolClassification = ToolClassification.NEUTRAL
    privilege: int = 0  # 0 = none, 1-3 = increasing real-world impact
    trust_of_output: TrustLevel = TrustLevel.TRUSTED
    reversible: bool = True
    description: str | None = None
    raw_decorator: str | None = None
    matched_pattern: str | None = None
    requires_approval: bool = False  # tool-level human-in-the-loop gate

    @property
    def is_source(self) -> bool:
        return self.classification in (ToolClassification.SOURCE, ToolClassification.BOTH)

    @property
    def is_sink(self) -> bool:
        return self.classification in (ToolClassification.SINK, ToolClassification.BOTH)


@dataclass
class Agent:
    """An LLM agent: a model + a set of tools + a system prompt + a guard config."""

    name: str
    location: SourceLocation
    framework: str  # "langgraph", "openai-agents", "mcp", ...
    tools: list[Tool] = field(default_factory=list)
    system_prompt_location: SourceLocation | None = None
    system_prompt_is_dynamic: bool = False  # built from f-string / .format / +
    system_prompt_taint_sources: list[str] = field(default_factory=list)
    interrupts_before: list[str] = field(default_factory=list)  # tool names gated by human approval
    interrupts_after: list[str] = field(default_factory=list)


@dataclass
class Finding:
    """A single detection emitted by a rule."""

    rule_id: str  # "IG001", ...
    rule_name: str
    severity: Severity
    location: SourceLocation
    message: str
    owasp_llm_ids: list[str] = field(default_factory=list)  # ["LLM01", "LLM06"]
    related_locations: list[SourceLocation] = field(default_factory=list)
    fix_hint: str | None = None
