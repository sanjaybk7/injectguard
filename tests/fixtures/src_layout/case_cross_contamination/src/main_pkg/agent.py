"""§4.6 — bidirectional cross-contamination negative test (review item #3).

``main_pkg/agent.py`` tries to import ``MAIN_PROMPT`` from its own
``prompts`` module, which DOES exist (``main_pkg/prompts.py``) but only
defines ``HELPER_PROMPT``, not ``MAIN_PROMPT``. The name ``MAIN_PROMPT``
exists over in ``helpers/prompts.py``; a name-anywhere fallback would
resolve there and silence IG002. Conservative-on-doubt requires IG002
to fire.

Paired with ``helpers/agent.py`` (the symmetric direction: imports
``HELPER_PROMPT`` from ``helpers.prompts``, where it isn't defined,
while ``HELPER_PROMPT`` exists in ``main_pkg.prompts``).

Expected: with both agents in this case-directory, IG002 fires twice
(once per direction). The test asserts the count, not just presence —
a single IG002 finding would mask either direction silently failing.
"""

from agents import Agent, function_tool

from main_pkg.prompts import MAIN_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="cross-contam-main-agent",
    instructions=MAIN_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
