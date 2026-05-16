"""Safe (post v0.2): aliased import — the alias must resolve to the imported literal."""

from agents import Agent, function_tool
from prompts import SYSTEM_PROMPT as SP


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="aliased-agent",
    instructions=SP,
    tools=[lookup],
    model="gpt-4o",
)
