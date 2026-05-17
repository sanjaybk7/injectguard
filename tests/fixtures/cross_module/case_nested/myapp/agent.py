"""Safe (post v0.2): absolute import from nested package."""

from agents import Agent, function_tool

from myapp.common.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="nested-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
