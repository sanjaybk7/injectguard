"""Safe: LangGraph agent with prompt= referencing a module-level constant."""

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

SYSTEM_PROMPT = "You are a helpful assistant. Be concise."


@tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


agent = create_react_agent(
    model="claude-opus-4-7",
    tools=[lookup],
    prompt=SYSTEM_PROMPT,
)
