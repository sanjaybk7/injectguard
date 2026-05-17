"""Safe (post v0.2): static prompt imported from sibling module."""

from agents import Agent, function_tool
from prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


agent = Agent(
    name="basic-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
