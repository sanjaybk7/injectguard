"""Safe (post v0.2): module attribute access (``import prompts; prompts.X``)."""

import prompts
from agents import Agent, function_tool


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="attribute-agent",
    instructions=prompts.SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
