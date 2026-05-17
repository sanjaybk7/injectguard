"""§1.1.1 (mixed orphan case) — review item #5b.

The src-layout detection wins because ``src/my_pkg/`` qualifies. The
orphan ``src/__init__.py`` is skipped with a warning at
``file_to_module_path`` time. This agent's cross-module import of
``SYSTEM_PROMPT`` still resolves normally via the package-relative path
``my_pkg.prompts``.

Expected:
* IG002 does NOT fire on this agent (normal resolution still works).
* A warning matching ``orphan __init__.py at package root`` is emitted
  exactly once for the scan (one orphan file).
"""

from agents import Agent, function_tool
from my_pkg.prompts import SYSTEM_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="src-orphan-agent",
    instructions=SYSTEM_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
