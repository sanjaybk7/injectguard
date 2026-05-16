"""Vulnerable (post v0.2): imported name is reassigned in source module."""

from agents import Agent, function_tool
from prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="multi-assign-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
