"""§4.5 — multi-package src-layout. pkg_a's agent imports from its own
sibling. Must resolve as ``pkg_a.prompts``, not ``src.pkg_a.prompts``.
"""

from agents import Agent, function_tool

from pkg_a.prompts import PROMPT_A


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-a-agent",
    instructions=PROMPT_A,
    tools=[lookup],
    model="gpt-4o",
)
