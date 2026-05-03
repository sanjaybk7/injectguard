"""Vulnerable: system prompt built from user request via f-string."""

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


@tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


def build_agent(user_request: str):
    return create_react_agent(
        model="claude-opus-4-7",
        tools=[lookup],
        prompt=f"You are an assistant. Context from request: {user_request}",
    )
