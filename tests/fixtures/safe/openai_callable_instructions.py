"""Safe: instructions= is a callable — the canonical OpenAI Agents SDK pattern
for context-aware prompts. Must NOT trigger IG002.

The SDK explicitly supports `def callable(run_context, agent) -> str` here.
A v1 enhancement could walk into the function body for taint, but at v0 we
treat it as a documented safe pattern.
"""

from agents import Agent, function_tool


def custom_instructions(run_context, agent) -> str:
    return "Respond as a haiku."


@function_tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


agent = Agent(
    name="haiku-agent",
    instructions=custom_instructions,
    tools=[lookup],
    model="gpt-4o",
)
