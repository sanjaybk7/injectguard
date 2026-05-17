"""Safe (post v0.2): top-level ``try: import X except ImportError: X = lit``.

This pattern is common (optional dependencies, version-specific imports). We
descend into top-level Try blocks for both imports and literal fallbacks.
The fallback ``SYSTEM_PROMPT = "..."`` in the except handler is also a
literal, so the resolved value is static either way.
"""

from agents import Agent, function_tool

try:
    from prompts import SYSTEM_PROMPT
except ImportError:  # pragma: no cover
    SYSTEM_PROMPT = "fallback prompt for environments without the prompts module"


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="try-import-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
