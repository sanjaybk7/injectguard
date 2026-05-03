"""Safe: send_email is gated behind a human-approval interrupt."""

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent


@tool
def read_email(message_id: str) -> str:
    """Fetch the body of an email by id."""
    return ""


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email on the user's behalf."""
    return ""


agent = create_react_agent(
    model="claude-opus-4-7",
    tools=[read_email, send_email],
    prompt="You are a helpful assistant.",
    interrupt_before=["send_email"],
)
