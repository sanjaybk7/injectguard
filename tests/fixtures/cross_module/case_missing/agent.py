"""Vulnerable (post v0.2): name imported but does not resolve in target module.

This is broken Python (would ImportError at runtime), but a static analyzer
can't assume runtime success. Conservative default: name unresolved → treat
as dynamic and flag.
"""

from agents import Agent, function_tool
from prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="missing-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
