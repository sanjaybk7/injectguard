"""IG001 — Confused-deputy: untrusted source flows to privileged sink without human approval.

This is the canonical agent-security failure: an agent has both a tool that returns
attacker-controllable text (email, web page, ticket, file) AND a tool that takes a
privileged action (sending email, transferring money, executing shell) — and the
LLM sits between them as the unwitting middleman.

Severity scoring:
  - Privilege of the sink (1-3) and reversibility drive the base severity.
  - If the source's trust_of_output is UNTRUSTED, severity is bumped one band.
  - If the sink is gated by `interrupt_before` (human-in-the-loop), the finding
    is suppressed (treated as mitigated).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from agentguard.ir import Finding, Severity, Tool, TrustLevel
from agentguard.rules.base import Rule, RuleContext


class ConfusedDeputyRule(Rule):
    id: ClassVar[str] = "IG001"
    name: ClassVar[str] = "Confused-deputy: untrusted source to privileged sink"
    owasp_llm_ids: ClassVar[list[str]] = ["LLM01", "LLM06"]

    def check(self, ctx: RuleContext) -> Iterable[Finding]:
        for agent in ctx.agents:
            sources = [t for t in agent.tools if t.is_source]
            sinks = [t for t in agent.tools if t.is_sink]
            if not sources or not sinks:
                continue

            for sink in sinks:
                if sink.privilege < 1:
                    continue
                if self._sink_is_gated(sink, agent.interrupts_before):
                    continue

                worst_source = self._select_worst_source(sources)
                if worst_source is None:
                    continue

                severity = self._severity(sink, worst_source)
                yield Finding(
                    rule_id=self.id,
                    rule_name=self.name,
                    severity=severity,
                    location=agent.location,
                    message=self._message(agent_factory=agent.name, source=worst_source, sink=sink),
                    owasp_llm_ids=list(self.owasp_llm_ids),
                    related_locations=[worst_source.location, sink.location],
                    fix_hint=self._fix_hint(sink),
                )

    @staticmethod
    def _sink_is_gated(sink: Tool, interrupts_before: list[str]) -> bool:
        return sink.requires_approval or sink.name in interrupts_before

    @staticmethod
    def _select_worst_source(sources: list[Tool]) -> Tool | None:
        ranked = sorted(
            sources,
            key=lambda t: (
                t.trust_of_output != TrustLevel.UNTRUSTED,  # untrusted first
                t.trust_of_output != TrustLevel.MIXED,
                -t.privilege,
            ),
        )
        return ranked[0] if ranked else None

    @staticmethod
    def _severity(sink: Tool, source: Tool) -> Severity:
        if sink.privilege >= 3 and not sink.reversible:
            base = Severity.CRITICAL
        elif sink.privilege >= 2 and not sink.reversible:
            base = Severity.HIGH
        elif sink.privilege >= 2:
            base = Severity.MEDIUM
        else:
            base = Severity.LOW

        if source.trust_of_output == TrustLevel.UNTRUSTED and base == Severity.MEDIUM:
            return Severity.HIGH
        return base

    @staticmethod
    def _message(agent_factory: str, source: Tool, sink: Tool) -> str:
        return (
            f"Agent created by `{agent_factory}` exposes an untrusted source `{source.name}` "
            f"and a privileged sink `{sink.name}` without a human-approval gate. "
            f"An attacker who controls the output of `{source.name}` can cause the agent to "
            f"invoke `{sink.name}` on the user's behalf (confused-deputy)."
        )

    @staticmethod
    def _fix_hint(sink: Tool) -> str:
        return (
            f"Add a human-in-the-loop checkpoint before `{sink.name}` runs. "
            f"LangGraph: `interrupt_before=[\"{sink.name}\"]` on the agent factory. "
            f"OpenAI Agents SDK: `tool_use_behavior=StopAtTools(stop_at_tool_names=[\"{sink.name}\"])` "
            f"or `tool_use_behavior=\"stop_on_first_tool\"`. "
            f"Alternatively, split into two agents with no shared LLM context between the "
            f"untrusted source and the privileged sink."
        )
