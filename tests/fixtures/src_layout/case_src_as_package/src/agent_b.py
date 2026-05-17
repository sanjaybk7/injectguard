"""Second file under the same user-named-src package. Exists to verify
that the discover-time warning fires *once* per scan, not once per file.
"""

from agents import Agent, function_tool

from src.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent_b = Agent(
    name="src-as-package-agent-b",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
