"""Safe (post v0.2): star import resolves to a literal in the starred module."""

from agents import Agent, function_tool
from prompts import *  # noqa: F403


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="star-agent",
    instructions=SYSTEM_PROMPT,  # noqa: F405
    tools=[lookup],
    model="gpt-4o",
)
