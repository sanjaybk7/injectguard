"""Vulnerable: web search results can drive shell execution."""

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


@tool
def search_web(query: str) -> str:
    """Search the web and return results."""
    return ""


@tool
def run_shell(command: str) -> str:
    """Run a shell command."""
    return ""


agent = create_react_agent(
    model="claude-opus-4-7",
    tools=[search_web, run_shell],
    prompt="You are a research assistant.",
)
