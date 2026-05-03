"""Vulnerable: OpenAI Agents SDK agent with dynamic system prompt."""

from agents import Agent, function_tool


@function_tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


def build_agent(user_request: str) -> Agent:
    return Agent(
        name="lookup-agent",
        instructions=f"You are an assistant. Context: {user_request}",
        tools=[lookup],
        model="gpt-4o",
    )
