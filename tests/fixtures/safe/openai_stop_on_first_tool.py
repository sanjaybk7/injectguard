"""Safe: tool_use_behavior='stop_on_first_tool' gates the sink."""

from agents import Agent, function_tool


@function_tool
def read_email(message_id: str) -> str:
    """Fetch an email."""
    return ""


@function_tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email."""
    return ""


agent = Agent(
    name="inbox-agent",
    instructions="You are a helpful assistant.",
    tools=[read_email, send_email],
    model="gpt-4o",
    tool_use_behavior="stop_on_first_tool",
)
