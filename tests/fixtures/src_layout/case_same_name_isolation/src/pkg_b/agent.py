"""§4a (review item #4 — content-isolation variant, paired with pkg_a/agent.py).

This agent imports ``PROMPT`` from ``pkg_b.shared_name``, where the
value is a plain string literal that Fix 1's symbol-table indexes
normally. The cross-module lookup must return the literal → IG002 stays
silent.

If isolation is broken and the symbol table returns ``pkg_a``'s dynamic
value (which would resolve to unresolved → IG002) in response to the
``pkg_b.shared_name.PROMPT`` lookup, IG002 would fire here unexpectedly.
The test asserts no IG002 on this file specifically.
"""

from agents import Agent, function_tool

from pkg_b.shared_name import PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-b-isolated-agent",
    instructions=PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
