"""Safe (post v0.2): aliased module attribute access (``import prompts as p; p.X``)."""

import prompts as p
from agents import Agent, function_tool


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="attribute-aliased-agent",
    instructions=p.SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
