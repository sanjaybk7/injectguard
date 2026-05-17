"""§1.2.2 — case sensitivity (review item #2).

The package on disk is ``src/Agents/`` (capital A). The import below uses
lowercase ``agents``. Python's import system would NOT match this on any
platform, regardless of filesystem case-sensitivity. Our analyzer must
behave the same way: ``Agents`` and ``agents`` are different modules.

Expected: IG002 fires (SYSTEM_PROMPT does not resolve, because the
indexed key is ``Agents.prompts`` but the import asks for
``agents.prompts``).

If this fixture starts passing (IG002 not firing), the implementation
has case-folded somewhere — that's a silent semantics change away from
Python's import model.
"""

from agents import Agent, function_tool

# Lowercase import, capital-A directory. Will not resolve.
from agents.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="case-sensitive-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
