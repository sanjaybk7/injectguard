"""§4.3 — mixed layout: this agent lives under src/. Both src/ and the
flat-layout helpers/ are scanned in the same run; this one imports from
its sibling under src.
"""

from agents import Agent, function_tool

from main_pkg.prompts import P1


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="mixed-main-agent",
    instructions=P1,
    tools=[lookup],
    model="gpt-4o",
)
