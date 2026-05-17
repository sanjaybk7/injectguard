"""§4.6 — bidirectional cross-contamination negative test (review item #3).

``helpers/agent.py`` tries to import ``HELPER_PROMPT`` from its own
``prompts`` module, but ``helpers/prompts.py`` only defines
``MAIN_PROMPT``. The name ``HELPER_PROMPT`` exists in
``main_pkg/prompts.py``; a name-anywhere fallback would resolve the
import there and silence IG002. Conservative-on-doubt requires IG002 to
fire.

Paired with ``src/main_pkg/agent.py`` (which exercises the symmetric
direction: imports ``MAIN_PROMPT`` from ``main_pkg.prompts``, where it
isn't defined, while ``MAIN_PROMPT`` exists in ``helpers.prompts``).

Expected: with both agents in this case-directory, IG002 fires twice
(once per direction). The test asserts the count, not just presence —
a single IG002 finding would mask either direction silently failing.
"""

from agents import Agent, function_tool

from helpers.prompts import HELPER_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="cross-contam-helpers-agent",
    instructions=HELPER_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
