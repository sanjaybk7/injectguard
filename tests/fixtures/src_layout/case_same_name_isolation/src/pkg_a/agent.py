"""§4a (review item #4 — content-isolation variant).

This agent imports ``PROMPT`` from ``pkg_a.shared_name``, where the
value is a *dynamic* f-string and therefore not indexed as a literal
by Fix 1's symbol-table. The cross-module lookup must return
unresolved → IG002 fires.

If isolation is broken and the symbol table returns ``pkg_b``'s literal
in response to the ``pkg_a.shared_name.PROMPT`` lookup, IG002 would
silently disappear from this agent. The test asserts the count on this
file specifically; the symmetric pkg_b assertion confirms pkg_b's
literal still resolves.
"""

from agents import Agent, function_tool

from pkg_a.shared_name import PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-a-isolated-agent",
    instructions=PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
