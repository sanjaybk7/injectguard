"""§2.4 (nested branch) — review item #3.

``my_pkg`` has ``__init__.py`` but its sub-directory ``my_pkg/sub/`` does
not. Per PEP 420 the runtime resolves ``my_pkg.sub`` as an implicit
namespace package; our analyzer aligns with the runtime, not with
strict-mode static-analysis defaults (mypy without ``--namespace-packages``,
historical pylint).
"""

from agents import Agent, function_tool

from my_pkg.sub.prompts import NESTED_PROMPT


@function_tool
def lookup(key: str) -> str:
    return ""


agent = Agent(
    name="nested-namespace-agent",
    instructions=NESTED_PROMPT,
    tools=[lookup],
    model="gpt-4o",
)
