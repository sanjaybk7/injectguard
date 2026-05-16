"""Vulnerable (post v0.2): the imported name resolves to a dynamically-built string.

We don't try to follow the dynamic construction across modules — too easy to
get wrong. Conservative default: if the export isn't a confirmed literal, fall
through to current dynamic-prompt behavior.
"""

from agents import Agent, function_tool
from prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="dynamic-remote-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
