"""IG002 — System prompt built from dynamic / untrusted input.

The system prompt is the highest-trust slot in any LLM call. If it's built at
runtime from user input or external data (f-string, .format(), concatenation,
loaded from a file/DB), an attacker who can influence that input can rewrite
the agent's instructions.

This rule fires when the system prompt for an agent is anything other than a
plain string literal. Severity is bumped if the variables interpolated look
user-controlled (request, user_input, message, query, body, content, etc.).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from agentic_guard.ir import Finding, Severity
from agentic_guard.rules.base import Rule, RuleContext

_USER_CONTROLLED_HINTS = {
    "request",
    "user_input",
    "userinput",
    "user",
    "message",
    "query",
    "body",
    "content",
    "text",
    "input",
    "raw",
    "params",
    "form",
    "data",
    "payload",
}


class SystemPromptInjectionRule(Rule):
    id: ClassVar[str] = "IG002"
    name: ClassVar[str] = "System prompt built from dynamic input"
    owasp_llm_ids: ClassVar[list[str]] = ["LLM01"]

    def check(self, ctx: RuleContext) -> Iterable[Finding]:
        for agent in ctx.agents:
            if not agent.system_prompt_is_dynamic or agent.system_prompt_location is None:
                continue

            taint_names = [n.lower() for n in agent.system_prompt_taint_sources]
            user_controlled = [n for n in taint_names if self._looks_user_controlled(n)]
            severity = Severity.HIGH if user_controlled else Severity.MEDIUM

            yield Finding(
                rule_id=self.id,
                rule_name=self.name,
                severity=severity,
                location=agent.system_prompt_location,
                message=self._message(agent_factory=agent.name, taints=agent.system_prompt_taint_sources),
                owasp_llm_ids=list(self.owasp_llm_ids),
                related_locations=[agent.location],
                fix_hint=(
                    "Keep the system prompt as a plain string constant. If you need "
                    "per-request behavior, pass user data as a separate user-role message "
                    "rather than interpolating it into the system prompt."
                ),
            )

    @staticmethod
    def _looks_user_controlled(name: str) -> bool:
        lowered = name.lower()
        return any(hint in lowered for hint in _USER_CONTROLLED_HINTS)

    @staticmethod
    def _message(agent_factory: str, taints: list[str]) -> str:
        if taints:
            joined = ", ".join(f"`{t}`" for t in taints)
            return (
                f"System prompt for agent `{agent_factory}` is constructed at runtime, "
                f"interpolating: {joined}. If any of these reach attacker-controlled data, "
                f"the agent's instructions can be overwritten."
            )
        return (
            f"System prompt for agent `{agent_factory}` is constructed at runtime rather "
            f"than being a string constant. Verify none of the inputs reach attacker-controlled data."
        )
