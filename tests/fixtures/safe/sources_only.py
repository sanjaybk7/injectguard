"""Safe: read-only agent with no privileged sinks."""

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


@tool
def search_web(query: str) -> str:
    """Search the web."""
    return ""


@tool
def read_email(message_id: str) -> str:
    """Read an email."""
    return ""


agent = create_react_agent(
    model="claude-opus-4-7",
    tools=[search_web, read_email],
    prompt="You are a research assistant. Summarize findings only — never act.",
)
