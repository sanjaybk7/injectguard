"""Safe: static system prompt as a string constant."""

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


@tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


agent = create_react_agent(
    model="claude-opus-4-7",
    tools=[lookup],
    prompt="You are an assistant. Be concise and accurate.",
)
