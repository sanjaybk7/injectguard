"""§1.1.1 (pure case) — review item #5a + user-named-src warning.

The user genuinely named their top-level package ``src``. No
subdirectory under ``src/`` contains ``.py`` files, so src-layout
detection rejects this layout and falls through to flat-layout. The
package is indexed as ``src``; ``src.prompts.SYSTEM_PROMPT`` resolves.

This file is one of two agents under the same package. The
discover-time warning ("flat-layout detected with top-level package
literally named 'src'...") must fire exactly once per scan, regardless
of how many files live under ``src/``.
"""

from agents import Agent, function_tool

from src.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent_a = Agent(
    name="src-as-package-agent-a",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
