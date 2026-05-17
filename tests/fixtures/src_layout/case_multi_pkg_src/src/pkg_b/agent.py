"""§4.5 — multi-package src-layout. pkg_b's agent imports from its own
sibling. Names must not bleed between pkg_a and pkg_b.
"""

from agents import Agent, function_tool

from pkg_b.prompts import PROMPT_B


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="pkg-b-agent",
    instructions=PROMPT_B,
    tools=[lookup],
    model="gpt-4o",
)
