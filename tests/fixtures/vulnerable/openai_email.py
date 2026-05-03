"""Vulnerable: OpenAI Agents SDK agent — confused-deputy via email tools."""

from agents import Agent, function_tool


@function_tool
def read_email(message_id: str) -> str:
    """Fetch the body of an email by id."""
    return ""


@function_tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email on the user's behalf."""
    return ""


agent = Agent(
    name="inbox-agent",
    instructions="You are a helpful assistant. Help the user manage their inbox.",
    tools=[read_email, send_email],
    model="gpt-4o",
)
