"""§4a paired fixture — see ``pkg_a/agent.py`` for the full rationale.

This agent must resolve ``PROMPT`` to pkg_b's value, not pkg_a's.
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
