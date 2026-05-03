"""Safe: instructions wrapped in the documented SDK helper.

`prompt_with_handoff_instructions(prompt)` is an OpenAI Agents SDK utility
that prepends boilerplate. Trust passes through to the wrapped argument.
"""

from agents import Agent, function_tool
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions


@function_tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


agent = Agent(
    name="orchestrator",
    instructions=prompt_with_handoff_instructions(
        "You are an orchestrator. Hand off to specialists when appropriate."
    ),
    tools=[lookup],
    model="gpt-4o",
)
