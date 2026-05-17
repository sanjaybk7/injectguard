"""§4.4 — PEP 420 namespace package under src-layout. ``my_pkg`` has no
``__init__.py`` but contains ``.py`` files. Python's runtime treats this
as a namespace package; the analyzer must too.
"""

from agents import Agent, function_tool
from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="namespace-pkg-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
