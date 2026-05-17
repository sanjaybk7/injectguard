"""§4.2 — pure flat-layout regression test for Fix 1's existing behavior.

This must continue to resolve after PR #4 lands. If PR #4 accidentally
breaks flat-layout, this fixture is the canary.
"""

from agents import Agent, function_tool

from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pure-flat-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
