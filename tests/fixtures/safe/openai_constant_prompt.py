"""Safe: instructions= references a module-level string constant.

This pattern dominates real-world agent code (FINANCIALS_PROMPT, RISK_PROMPT,
etc. seen across openai-agents-python and openai-cookbook examples). It is
functionally identical to a string literal and must NOT trigger IG002.
"""

from agents import Agent, function_tool

ANALYST_PROMPT = (
    "You are a financial analyst focused on company fundamentals. "
    "Be concise and accurate."
)


@function_tool
def lookup(key: str) -> str:
    """Look up a value."""
    return ""


agent = Agent(
    name="analyst-agent",
    instructions=ANALYST_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
