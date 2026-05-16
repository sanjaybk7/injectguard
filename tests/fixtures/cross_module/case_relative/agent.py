"""Safe (post v0.2): relative import (``from .prompts import X``)."""

from agents import Agent, function_tool

from .prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="relative-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
