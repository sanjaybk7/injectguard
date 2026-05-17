"""§4.6 — cross-contamination negative test.

``main_pkg/agent.py`` tries to import ``MAIN_PROMPT`` from its own
``prompts`` module, which does NOT exist. The name ``MAIN_PROMPT`` *does*
exist over in ``helpers/prompts.py``, but a name-anywhere fallback
lookup would be a bug: imports are resolved by exact module path, not by
name presence. IG002 must fire here.

If someone "helpfully" adds a fallback that searches every module for the
name, this fixture catches it.
"""

from agents import Agent, function_tool

from main_pkg.prompts import MAIN_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="cross-contam-agent",
    instructions=MAIN_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
