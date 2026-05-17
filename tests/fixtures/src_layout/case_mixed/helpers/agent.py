"""§4.3 — mixed layout: this agent lives at flat-layout root. Imports from
helpers.prompts (its own sibling). Both this agent and the src-layout one
must resolve in the same scan.
"""

from agents import Agent, function_tool

from helpers.prompts import P2


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="mixed-helpers-agent",
    instructions=P2,
    tools=[lookup],
    model="gpt-4o",
)
